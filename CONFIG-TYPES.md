# CONFIG-TYPES: 四个正则配置键的类型校验读数与分层分析

探针：`repro/config-regex-key-validation.py`（`.venv/bin/python` 运行，八组 `[tool.black]` 单键配置）。
环境：black 26.5.1，click 8.5.0，Python 3.14。

## 一、八组读数（基线，照实抄自探针输出）

```
--- [tool.black] exclude = ["a"]
    rc=2  stderr=['Usage: black [OPTIONS] SRC ...', "Try 'black --help' for help."]
    files black actually processed: [] (of ['a1.py', 'b2.py', 'c3.py'])
--- [tool.black] extend-exclude = ["a"]
    rc=2  stderr=['Usage: black [OPTIONS] SRC ...', "Try 'black --help' for help."]
    files black actually processed: [] (of ['a1.py', 'b2.py', 'c3.py'])
--- [tool.black] force-exclude = ["a"]
    rc=0  stderr=[]
    files black actually processed: ['b2.py already well formatted, good job.', 'c3.py already well formatted, good job.'] (of ['a1.py', 'b2.py', 'c3.py'])
--- [tool.black] include = ["a"]
    rc=0  stderr=[]
    files black actually processed: ['a1.py already well formatted, good job.'] (of ['a1.py', 'b2.py', 'c3.py'])
--- [tool.black] include = {a = 1}
    rc=0  stderr=[]
    files black actually processed: [] (of ['a1.py', 'b2.py', 'c3.py'])
--- [tool.black] per-file-ignores = ["a"]
    rc=0  stderr=["Invalid config keys detected: 'per_file_ignores' (in /tmp/bkcfgqofffh_b/pyproject.toml)"]
    files black actually processed: ['a1.py already well formatted, good job.', 'b2.py already well formatted, good job.', 'c3.py already well formatted, good job.'] (of ['a1.py', 'b2.py', 'c3.py'])
--- [tool.black] target-version = "py311"
    rc=2  stderr=['Usage: black [OPTIONS] SRC ...', "Try 'black --help' for help."]
    files black actually processed: [] (of ['a1.py', 'b2.py', 'c3.py'])
--- [tool.black] preview = 1
    rc=0  stderr=[]
    files black actually processed: ['a1.py already well formatted, good job.', 'b2.py already well formatted, good job.', 'c3.py already well formatted, good job.'] (of ['a1.py', 'b2.py', 'c3.py'])
```

两点说明：

- `per-file-ignores` 那行 stderr 里的 `/tmp/bkcfgXXXXXXXX_X/` 是 `tempfile.mkdtemp` 的随机目录名，每次运行都不同，逐字对时这一段必然对不上，属探针本身的不确定性，其余内容稳定。
- 探针 stderr 只截了前两行（`Usage:` / `Try 'black --help'`）。rc=2 各案的完整报错正文（第 4 行）分别为：
  - `Error: Config key exclude must be a string`
  - `Error: Config key extend-exclude must be a string`
  - `Error: Config key target-version must be a list`

八组按行为归四类：

| 组 | 退出码 | 行为 |
|---|---|---|
| `exclude` / `extend-exclude` 列表、`target-version` 字符串 | 2 | 干净报错，零文件被碰 |
| `force-exclude` / `include` 列表、`include` 表 | 0 | 一声不吭，只处理部分（或零个）文件 |
| `per-file-ignores`（不存在的键） | 0 | stderr 红字警告 "Invalid config keys detected"，键被忽略，全部文件照常处理 |
| `preview = 1`（布尔键给整数） | 0 | 完全静默接受（见下文分层第 2、3 层） |

## 二、配置值从 pyproject.toml 到命令行经过的层

1. **TOML 解析层** — `parse_pyproject_toml`（`src/black/files.py:121`）：tomllib 解析后取出 `[tool.black]`，键名做 `-`→`_` 归一化。**不做任何类型校验**，TOML 列表、表原样保留在 dict 里。
2. **配置回调层** — `read_pyproject_toml`（`src/black/__init__.py:116`，作为 `--config` 的 eager 回调执行）：
   - `spellcheck_pyproject_toml_keys`（`src/black/__init__.py:181`）：只对**未知键**发警告（`out()` 走 stderr），不改退出码——这就是 `per-file-ignores` 那组 rc=0 带红字的原因。
   - sanitize（`src/black/__init__.py:145`）：值不是 list/dict 就 `str(v)`（所以 `preview = 1` 变成字符串 `"1"`，`verbose = 1` 同理）；**list 和 dict 原样放行**。
   - 显式 `isinstance` 校验只有四处：`target_version` 必须是 list、`exclude` 必须是 str、`extend_exclude` 必须是 str、`line_ranges` 禁用（`src/black/__init__.py:150-170`）。**`include` 和 `force_exclude` 没有对应检查**，列表/表直接漏进 `ctx.default_map`。
3. **click 类型层**：四个键的选项都是 `type=str`（`src/black/__init__.py:412/425/434/455`）。default_map 里的默认值同样要过参数类型转换；click 8.5.0 的 `StringParamType.convert` 对非 str 非 bytes 的值一律 `return str(value)` 兜底——列表 `["a"]` 变成字符串 `"['a']"`，表 `{"a": 1}` 变成 `"{'a': 1}"`。**这一层也不报错**。（`preview` 是 `is_flag=True`，BOOL 类型把 `"1"` 转成 `True`，同样静默。）
4. **回调编译层** — `validate_regex`（`src/black/__init__.py:244`，四个键都挂了它）：对拿到的**字符串** `re_compile_maybe_verbose`。`"['a']"` 和 `"{'a': 1}"` 都是合法正则，编译通过，于是 rc=0 放行。
5. **匹配层** — `gen_python_files`（`src/black/files.py:320`）：`include.search(root_relative_path)`，匹配的是相对项目根的 `/a1.py` 这种形态的路径（不含 mkdtemp 随机目录名，所以读数稳定）。

**为什么列表在前两层都不报错**：第 1 层压根不做类型校验；第 2 层的显式校验是白名单式的，只写了 `exclude`/`extend-exclude`/`target-version`/`line-ranges` 四处，`include`/`force-exclude` 漏了；第 3 层 click 的 str 类型对任何值都 `str()` 兜底而不是拒绝。三层叠加，错误类型的值被悄悄 `str()` 成一个"碰巧合法"的正则。

**`include` 写成表时编出来的正则在匹配什么**：

- `include = ["a"]` → `str()` 后是 `"['a']"`。作为正则这是一个**字符类**，匹配任意含 `a` 或 `'` 字符的路径。`/a1.py` 含 `a` → 入选；`/b2.py`、`/c3.py` 不含 → 被 include 挡掉。所以"只格式化了部分文件"。
- `include = {a = 1}` → `str()` 后是 `"{'a': 1}"`。Python `re` 对不在合法量词位置的 `{`/`}` 按字面字符处理，整个模式就是 9 个字符的**字面串** `{'a': 1}`，只匹配包含该子串的路径——真实文件路径里不存在，于是 include 一个文件都不放行，零文件被处理，rc=0。
- `force-exclude = ["a']` 同理：`"['a']"` 字符类把含 `a` 的 `a1.py` 硬排除，剩下 `b2.py`、`c3.py` 被处理。

## 三、两种候选修法的对照实验

仓库拷到仓库外两份（venv 是可编辑安装，`.pth` 指向 seed，故跑拷贝一律带 `PYTHONPATH=<拷贝>/src` 指回拷贝自己；已用 `black.__file__` 验证导入的是拷贝）：

- **拷贝 A `/tmp/t49-fixA`**：在 `read_pyproject_toml` 里给 `include`、`force-exclude` 补与 `exclude` 同款的 `isinstance` 校验（`src/black/__init__.py`）。
- **拷贝 B `/tmp/t49-fixB`**：把 `src/black/resources/black.schema.json` 里 `include`、`force-exclude` 两键的 `"type": "string"` 放宽为 `"type": ["string", "array"]`。

### 拷贝 A 的三组关键读数

```
--- [tool.black] force-exclude = ["a"]
    rc=2  stderr=['Usage: black [OPTIONS] SRC ...', "Try 'black --help' for help."]
    files black actually processed: [] (of ['a1.py', 'b2.py', 'c3.py'])
--- [tool.black] include = ["a"]
    rc=2  stderr=['Usage: black [OPTIONS] SRC ...', "Try 'black --help' for help."]
    files black actually processed: [] (of ['a1.py', 'b2.py', 'c3.py'])
--- [tool.black] include = {a = 1}
    rc=2  stderr=['Usage: black [OPTIONS] SRC ...', "Try 'black --help' for help."]
    files black actually processed: [] (of ['a1.py', 'b2.py', 'c3.py'])
```

完整报错正文：`Error: Config key force-exclude must be a string`、`Error: Config key include must be a string`。

### 拷贝 B 的三组关键读数（与基线逐字相同）

```
--- [tool.black] force-exclude = ["a"]
    rc=0  stderr=[]
    files black actually processed: ['b2.py already well formatted, good job.', 'c3.py already well formatted, good job.'] (of ['a1.py', 'b2.py', 'c3.py'])
--- [tool.black] include = ["a"]
    rc=0  stderr=[]
    files black actually processed: ['a1.py already well formatted, good job.'] (of ['a1.py', 'b2.py', 'c3.py'])
--- [tool.black] include = {a = 1}
    rc=0  stderr=[]
    files black actually processed: [] (of ['a1.py', 'b2.py', 'c3.py'])
```

### 套件结论（`pytest tests/test_schema.py tests/test_black.py tests/test_format.py`）

| 对象 | 结果 |
|---|---|
| 基线（本仓库） | 373 passed, 4 subtests passed |
| 拷贝 A（补运行时校验） | 373 passed, 4 subtests passed |
| 拷贝 B（放宽 schema） | 373 passed, 4 subtests passed |

**拷贝 B 根本没碰到运行时**：`black.schema:get_schema` 只挂在 `pyproject.toml` 的 `validate_pyproject.tool_schema` entry point 上（`pyproject.toml:113-114`），供 validate-pyproject 之类的外部校验器和 `tests/test_schema.py` 消费；black 运行时（`src/black/__init__.py`、`files.py`、`blackd`）没有任何一处 import 它。所以放宽 schema 后八组读数与基线逐字相同——静默部分格式化的问题原样保留，只是让外部校验器也不再能替你挡下这类错误配置。schema 现状（四键均 `"type": "string"`）本来就是对的，不该动。

（环境备注：本仓库 checkout 缺了一批被 .gitignore 盖住的上游测试夹具文件——`tests/data/include_exclude_tests/b/dont_exclude/` 等 9 处，已从同源 seed 拷回补齐；补齐前基线 `test_black.py` 有 10 个与本次主题无关的夹具缺失失败，补齐后方为上表的全绿基线。）

## 四、统一规则建议

四个正则键 `exclude` / `extend-exclude` / `force-exclude` / `include` 在 pyproject.toml 里一律只接受 **TOML 字符串**，校验分两道：

1. **类型道**（`read_pyproject_toml`，与现有两键同位置同款）：
   - 非字符串（列表、表、整数……）→ `raise click.BadOptionUsage("<key>", "Config key <key> must be a string")`；
   - 报错形态：stderr 输出 `Usage:` 前缀加 `Error: Config key <key> must be a string`，**退出码 2**，一个文件都不处理。
   - `exclude`、`extend-exclude` 现有文案 `Config key exclude must be a string` / `Config key extend-exclude must be a string` **原样保留**；新补两键用同款句式 `Config key force-exclude must be a string`、`Config key include must be a string`，四键文案对齐。
2. **内容道**（`validate_regex`，四键已全覆盖，不动）：字符串不是合法正则 → `click.BadParameter`，`Error: Not a valid regular expression: ...`，退出码 2（`test_invalid_cli_regex` 已守）。

配套地，`black.schema.json` 四键维持 `"type": "string"` 不变——schema 与运行时规则一致，外部校验器和 black 自身报错互为冗余而非互相矛盾。
