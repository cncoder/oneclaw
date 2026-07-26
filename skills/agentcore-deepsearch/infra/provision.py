"""一键开通 AgentCore Web Search Tool：建 IAM 角色 → 建 Gateway(AWS_IAM 入站) → 加 web-search connector target → 轮询 READY。

幂等：重复跑会复用同名角色 / Gateway / target，不重复创建。
全程 us-east-1（Web Search 目前唯一支持区），无任何公网入站。
"""

from __future__ import annotations

import json
import time

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
ROLE_NAME = "AgentCoreWebSearchGatewayRole"
GATEWAY_NAME = "websearch-gw"
TARGET_NAME = "web-search-tool"

iam = boto3.client("iam")
acc = boto3.client("sts").get_caller_identity()["Account"]
agc = boto3.client("bedrock-agentcore-control", region_name=REGION)

trust_policy = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "AllowAgentCoreToAssumeRole",
            "Effect": "Allow",
            "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
            "Action": "sts:AssumeRole",
            "Condition": {
                "StringEquals": {"aws:SourceAccount": acc},
                "ArnLike": {
                    "aws:SourceArn": f"arn:aws:bedrock-agentcore:{REGION}:{acc}:gateway/*"
                },
            },
        }
    ],
}

perm_policy = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "InvokeGateway",
            "Effect": "Allow",
            "Action": "bedrock-agentcore:InvokeGateway",
            "Resource": f"arn:aws:bedrock-agentcore:{REGION}:{acc}:gateway/*",
        },
        {
            "Sid": "InvokeWebSearch",
            "Effect": "Allow",
            "Action": "bedrock-agentcore:InvokeWebSearch",
            "Resource": f"arn:aws:bedrock-agentcore:{REGION}:aws:tool/web-search.v1",
        },
    ],
}


def ensure_role() -> str:
    try:
        r = iam.create_role(
            RoleName=ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description="AgentCore Gateway execution role for Web Search Tool",
        )
        arn = r["Role"]["Arn"]
        print(f"[role] created {arn}")
    except ClientError as e:
        if e.response["Error"]["Code"] != "EntityAlreadyExists":
            raise
        arn = iam.get_role(RoleName=ROLE_NAME)["Role"]["Arn"]
        iam.update_assume_role_policy(
            RoleName=ROLE_NAME, PolicyDocument=json.dumps(trust_policy)
        )
        print(f"[role] reuse {arn}")
    iam.put_role_policy(
        RoleName=ROLE_NAME,
        PolicyName="WebSearchInvoke",
        PolicyDocument=json.dumps(perm_policy),
    )
    print("[role] inline policy WebSearchInvoke attached")
    return arn


def ensure_gateway(role_arn: str) -> tuple[str, str]:
    for g in agc.list_gateways(maxResults=100).get("items", []):
        if g["name"] == GATEWAY_NAME:
            gid = g["gatewayId"]
            full = agc.get_gateway(gatewayIdentifier=gid)
            print(f"[gateway] reuse {gid} ({full['status']})")
            return gid, full["gatewayUrl"]
    # IAM 角色刚建好，信任关系可能还没全局生效，重试几次
    last = None
    for _ in range(6):
        try:
            r = agc.create_gateway(
                name=GATEWAY_NAME,
                roleArn=role_arn,
                protocolType="MCP",
                authorizerType="AWS_IAM",
                description="Managed Amazon Web Search via AgentCore Gateway",
            )
            print(f"[gateway] created {r['gatewayId']} ({r['status']})")
            return r["gatewayId"], r["gatewayUrl"]
        except ClientError as e:
            last = e
            print(f"[gateway] create retry: {e.response['Error']['Code']}")
            time.sleep(5)
    raise last


def ensure_target(gid: str) -> None:
    for t in agc.list_gateway_targets(gatewayIdentifier=gid, maxResults=100).get(
        "items", []
    ):
        if t["name"] == TARGET_NAME:
            print(f"[target] reuse {t['targetId']} ({t['status']})")
            tid = t["targetId"]
            break
    else:
        r = agc.create_gateway_target(
            gatewayIdentifier=gid,
            name=TARGET_NAME,
            targetConfiguration={
                "mcp": {
                    "connector": {
                        "source": {"connectorId": "web-search"},
                        "configurations": [
                            {"name": "WebSearch", "parameterValues": {}}
                        ],
                    }
                }
            },
            credentialProviderConfigurations=[
                {"credentialProviderType": "GATEWAY_IAM_ROLE"}
            ],
        )
        tid = r["targetId"]
        print(f"[target] created {tid} ({r['status']})")

    for _ in range(20):
        t = agc.get_gateway_target(gatewayIdentifier=gid, targetId=tid)
        st = t["status"]
        if st == "READY":
            print(f"[target] READY")
            return
        if st == "FAILED":
            raise RuntimeError(f"target FAILED: {t.get('statusReasons')}")
        print(f"[target] waiting... {st}")
        time.sleep(3)
    raise TimeoutError("target not READY in time")


if __name__ == "__main__":
    role_arn = ensure_role()
    time.sleep(8)  # 等 IAM 角色全局传播
    gid, url = ensure_gateway(role_arn)
    ensure_target(gid)
    print("\n=== DONE ===")
    print(f"GATEWAY_ID={gid}")
    print(f"GATEWAY_URL={url}")
    print(f"ROLE_ARN={role_arn}")
