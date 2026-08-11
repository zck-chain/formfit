# 数据库迁移（Alembic）

本项目使用 [Alembic](https://alembic.readthedocs.io/) 管理 schema 变更。数据库连接串从应用配置读取（`app.core.config.settings.database_url`，即环境变量 `DATABASE_URL`），`alembic.ini` 中的 URL 仅为占位。

## 常用命令

```bash
# 对当前 DATABASE_URL 指向的库升级到最新
python -m alembic upgrade head

# 回滚一个版本
python -m alembic downgrade -1

# 查看当前版本
python -m alembic current

# 修改模型后，自动生成迁移脚本
python -m alembic revision --autogenerate -m "describe change"
```

生成迁移后务必检查脚本内容（autogenerate 不总完美，尤其 SQLite 的 ALTER 限制），再提交。

## 初始化场景

- **全新数据库**：直接 `python -m alembic upgrade head`，会从基线 `1e495f38fedb` 建出全部表。
- **已有历史库**（在启用 Alembic 之前由 `Base.metadata.create_all` 建表、schema 与基线一致）：
  ```bash
  python -m alembic stamp head
  ```
  这会只写入 `alembic_version` 标记，不重复建表；之后的迁移即可正常 `upgrade head`。

## 注意

- 启动时 `app.startup.init_db` 仍调用 `create_all`（幂等，仅补建缺失表），方便本地开发；
  生产环境以 `alembic upgrade head` 为准，不要依赖 `create_all` 做 schema 演进。
- SQLite 下迁移以 batch 模式生成（`render_as_batch=True`），兼容其有限的 ALTER 能力。
