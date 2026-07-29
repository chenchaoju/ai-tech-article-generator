import argparse
import os

import paramiko


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("local_path")
    parser.add_argument("remote_path")
    args = parser.parse_args()

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        os.environ["DEPLOY_HOST"],
        username=os.environ["DEPLOY_USER"],
        password=os.environ["DEPLOY_PASSWORD"],
        timeout=12,
        auth_timeout=12,
        banner_timeout=12,
    )
    try:
        with client.open_sftp() as sftp:
            sftp.put(args.local_path, args.remote_path)
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
