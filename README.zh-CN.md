# Scope Lineage

中文 | [English](README.md)

Scope Lineage 是面向 Spark/Hive SQL 的 scope 感知字段级血缘解析器。它对 SQL 做静态分析，
结合可选的通用 Schema/DDL 元数据，输出两份版本化产物：

- `lineage.json`：scope 图、字段映射、端到端血缘和解析状态；
- `diagnostics.json`：详细告警与降级证据。

本仓库只包含首期开源的基础层，不包含数仓建模、业务域 Preset、Insight 报告或重构建议。

## 从源码安装

```bash
git clone https://github.com/realyin/sparksql-knowleage-parse.git
cd sparksql-knowleage-parse
python -m pip install -e ".[dev]"
```

首个包版本已准备为 `scope-lineage 0.1.0`；在上传到包索引前，请从本仓库安装。

## 命令行

```bash
scope-lineage parse \
  --sql-file examples/simple_insert.sql \
  --schema examples/table_cols.csv \
  --out /tmp/scope-lineage
```

该命令只生成：

```text
/tmp/scope-lineage/simple_insert/
  lineage.json
  diagnostics.json
```

当 INSERT 投影需要按权威目标字段顺序绑定时，可传入 `--target-ddl-metadata`。只有调用方明确接受
失败语句仍带诊断落盘时，才应使用 `--allow-partial`。

## Python API

```python
from lineage_parser import parse_scope_lineage, to_lineage_dict, write_lineage

result = parse_scope_lineage(
    "INSERT INTO mart.user_ids SELECT id FROM ods.users",
    task_id="user_ids",
    schema={"ods.users": ["id"]},
)

document = to_lineage_dict(result)
write_lineage(result, "/tmp/scope-lineage/user_ids")
```

稳定公共面由 `lineage_parser.PUBLIC_CORE_API` 显式声明。下游应使用这个公共门面或读取 JSON
契约，不应穿透导入内部实现模块。

## 契约兼容性

两份输出都要求 `schema_version: "1.0"`，并在写盘前强制校验。同一 major 版本内，消费者应
容忍新增可选字段；删除、改名或改变字段语义必须升级 major。

- [Lineage JSON 契约](docs/zh-CN/lineage-json.md)
- [Diagnostics JSON 契约](docs/zh-CN/diagnostics-json.md)

## 范围与限制

- Spark/Hive 方言，只做静态分析，不执行 SQL；
- 主要面向 `INSERT`、`MERGE` 数仓落表语句；
- 保留 CTE、子查询、UNION 分支、聚合、窗口和中间 scope；
- 缺少 Schema 时，`SELECT *` 可能保留为显式降级占位；
- 不支持或恢复解析的语法，会通过状态和 diagnostics 明确呈现。

## 开发验证

```bash
python -m pip install -e ".[dev]"
python -m pytest -q tests/core tests/architecture/test_core_boundaries.py
python -m ruff check lineage_parser tests
python -m build
python tests/architecture/verify_distribution.py dist/*
```

提交示例或解析修改前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md) 和 [SECURITY.md](SECURITY.md)。
所有 fixture 必须是合成数据，不得包含私有 SQL、标识符或本机路径。

## License

Apache License 2.0，见 [LICENSE](LICENSE)。
