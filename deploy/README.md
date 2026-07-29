# 文章工坊服务器部署

部署目录：`/opt/article-workshop`

访问路径：

- 前端：`http://117.72.246.88/article-workshop/`
- 后端：`http://117.72.246.88/article-workshop/api/`
- API 文档：`http://117.72.246.88/article-workshop/api/docs`

## 与公用服务的关系

项目自身的 `docker-compose.production.yml` 只运行：

- `article_workshop_db`
- `article_workshop_api`
- `article_workshop_web`

三个容器均不会占用服务器的 80 端口。前端与 API 通过服务器现有的公用
Nginx 暴露。`deploy/default.conf` 是根据用户提供的公用配置制作的增量版本，
保留了原来的云记账、异常处理、材料转换和文件助手配置。

部署前需要执行：

```bash
docker inspect app_stack_web \
  --format '{{range $name, $_ := .NetworkSettings.Networks}}{{$name}}{{"\n"}}{{end}}'
```

将返回的公用网络名称填写到 `.env.production` 的 `PUBLIC_NETWORK`。

然后：

```bash
cd /opt/article-workshop
cp .env.production.example .env.production
# 填入 GLM_API_KEY，并确认 PUBLIC_NETWORK
docker compose -f docker-compose.production.yml --env-file .env.production up -d --build
```

确认三个容器健康后，将 `deploy/default.conf` 替换到公用 Nginx 当前挂载的
配置文件位置，先执行 `nginx -t`，通过后再重载公用 Nginx。
