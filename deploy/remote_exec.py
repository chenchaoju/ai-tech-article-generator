import argparse
import os
import sys

import paramiko


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command")
    args = parser.parse_args()
    host = os.environ["DEPLOY_HOST"]
    username = os.environ["DEPLOY_USER"]
    password = os.environ["DEPLOY_PASSWORD"]

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        host,
        username=username,
        password=password,
        timeout=12,
        auth_timeout=12,
        banner_timeout=12,
    )
    try:
        _, stdout, stderr = client.exec_command(args.command, timeout=1200)
        output = stdout.read().decode("utf-8", errors="replace")
        error = stderr.read().decode("utf-8", errors="replace")
        if output:
            sys.stdout.buffer.write(output.encode("utf-8", errors="replace"))
        if error:
            sys.stderr.buffer.write(error.encode("utf-8", errors="replace"))
        return stdout.channel.recv_exit_status()
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
