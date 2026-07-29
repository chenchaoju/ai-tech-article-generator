from datetime import datetime, timezone
from pathlib import Path
import shutil


CONFIG_PATH = Path("/opt/app_stack/nginx/default.conf")
MARKER = "# 文章工坊：独立路径，不占用现有 /api/"
ANCHOR = "\n}\n\nserver {\n    listen 80;\n    server_name ccj.whispery.cn;"
BLOCK = """

    # 文章工坊：独立路径，不占用现有 /api/
    location = /article-workshop {
        return 301 /article-workshop/;
    }

    location /article-workshop/api/ {
        proxy_pass http://article_workshop_api:8000;
        proxy_http_version 1.1;
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /article-workshop/ {
        proxy_pass http://article_workshop_web:80/;
        proxy_http_version 1.1;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
"""


def main() -> None:
    content = CONFIG_PATH.read_text(encoding="utf-8")
    if MARKER in content:
        print("文章工坊 Nginx 配置已存在，无需重复写入")
        return
    if ANCHOR not in content:
        raise RuntimeError("找不到公用 Nginx 第一个 server 块的安全插入位置")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    backup = CONFIG_PATH.with_name(f"default.conf.backup-{timestamp}")
    shutil.copy2(CONFIG_PATH, backup)
    content = content.replace(ANCHOR, f"{BLOCK}{ANCHOR}", 1)
    CONFIG_PATH.write_text(content, encoding="utf-8")
    print(f"已写入文章工坊 Nginx 配置；备份：{backup}")


if __name__ == "__main__":
    main()
