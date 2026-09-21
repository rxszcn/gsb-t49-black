# 四个正则配置键的类型校验现状与实验记录

运行环境：仓库根目录，`.venv/bin/python repro/config-regex-key-validation.py`（venv 为可编辑安装，`import black` 解析到的 `src/black` 与本仓库逐字节一致，已用 `diff -rq` 核对）。

## 一、基线读数（仓库未动，八组照实抄录）

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
    rc=0  stderr=["Invalid config keys detected: 'per_file_ignores' (in /tmp/bkcfgp933cadx/pyproject.toml)"]
    files black actually processed: ['a1.py already well formatted, good job.', 'b2.py already well formatted, good job.', 'c3.py already well formatted, good job.'] (of ['a1.py', 'b2.py', 'c3.py'])
--- [tool.black] target-version = "py311"
    rc=2  stderr=['Usage: black [OPTIONS] SRC ...', "Try 'black --help' for help."]
    files black actually processed: [] (of ['a1.py', 'b2.py', 'c3.py'])
--- [tool.black] preview = 1
    rc=0  stderr=[]
    files black actually processed: ['a1.py already well formatted, good job.', 'b2.py already well formatted, good job.', 'c3.py already well formatted, good job.'] (of ['a1.py', 'b2.py', 'c3.py'])
```

四个正则键里，`exclude` / `extend-exclude` 有校验（列表 → rc=2，一个文件不碰），`force-exclude` / `include` 没有（列表 → rc=0，静默处理部分文件）。

## 二、配置值从 pyproject.toml 到命令行经过的三层

1. **TOML 解析层** — `parse_pyproject_toml`（`src/black/files.py:121`）：把 `[tool.black]` 表读成 dict，键名 `-` 换成 `_`。不做任何类型检查，列表、表、整数原样保留。
2. **配置读取层** — `read_pyproject_toml`（`src/black/__init__.py:116`），依次做四件事：
   - `spellcheck_pyproject_toml_keys`：未知键只打印红色警告，**不影响退出码、不中止运行**；
   - sanitize：`str(v) if not isinstance(v, (list, dict)) else v`——**列表和表被显式豁免**，原样放行；
   - 显式 isinstance 检查：全仓库只写了三个键——`target_version`（必须是 list）、`exclude`（必须是 str）、`extend_exclude`（必须是 str），外加 `line_ranges` 禁用。`include` / `force_exclude` 不在其列；
   - 剩下的键值并入 `ctx.default_map`，变成 click 参数的默认值。
3. **click 转换层**：default_map 的值先过参数的 `type=str`（`StringParamType.convert`，click 8.5.0）：非 str 一律 `str(value)`；再过回调 `validate_regex`（`src/black/__init__.py:245`）用 `re_compile_maybe_verbose` 编译。

**为什么列表在前两层都不报错**：第一层根本不查类型；第二层的 sanitize 明确把 list/dict 排除在 `str()` 之外，而显式 isinstance 检查只覆盖了 `exclude` / `extend-exclude` 两个键。到了第三层，click 把 `["a"]` 转成字符串 `"['a']"`——它恰好是语法合法的正则，`validate_regex` 也放行。于是层层全过，一声不吭。

**`include = {a = 1}` 编出来的正则到底在匹配什么**：TOML 表变成 dict `{'a': 1}`，经 click `str()` 成 `"{'a': 1}"` 再编译。`{` 在 Python re 里构不成合法量词就按字面量处理，整个模式等价于匹配字面子串 `{'a': 1}`。include 匹配的对象是根相对路径（`src/black/files.py:355` 加前导 `/`，`:404` 做 `include.search`），`/a1.py`、`/b2.py`、`/sub/c3.py` 都不含这串字符 → 0 个文件被处理，rc=0。

对照组：`include = ["a"]` → `"['a']"` 是**字符类**，匹配任何含 `a` 或 `'` 的路径 → 只有 `a1.py` 命中；`force-exclude = ["a"]` 同款字符类 → `a1.py` 被排除，只处理 `b2.py`、`c3.py`。这就是"只格式化了部分文件"的全部机理。

**另外几组藏着的暗账**：

- `per-file-ignores = ["a"]`：未知键只触发 spellcheck 警告，rc=0，三个文件照常处理——警告既不改退出码也不阻止运行。
- `target-version = "py311"`（字符串而非列表）：被第二层显式检查拦下，rc=2。它是除 `exclude` / `extend-exclude` 外唯一有运行时类型检查的键。
- `preview = 1`：整数在第二层被 sanitize 成 `"1"`，click 的 BoolParamType 把 `"1"` 当 True 收下，rc=0 一声不吭——布尔键收整数同样无校验。

## 三、两份仓库外拷贝的候选修法实验

拷贝方法：`git archive HEAD` 解到 `/tmp/t49-copyA`、`/tmp/t49-copyB`，软链 `.venv` 指回原 venv，运行时一律 `PYTHONPATH=<拷贝>/src`（已验证 `black.__file__` 落在拷贝内）。注意 `git archive` 只导出被跟踪文件，`tests/data` 下一批被 gitignore 的用例数据（如 `include_exclude_tests/b/dont_exclude`）会丢，直接跑套件会白挂 10 个用例；已把缺失数据补齐后再跑，下述结论均为补齐后的结果。

### 拷贝 A：给 include / force-exclude 补同款按键校验（改运行时）

改法：`src/black/__init__.py` 的 `read_pyproject_toml` 里，照 `extend_exclude` 的样式补两段——`force_exclude` / `include` 非 str 即 `raise click.BadOptionUsage(..., "Config key ... must be a string")`。

三组关键读数：

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

完整报错尾行实测为 `Error: Config key include must be a string` / `Error: Config key force-exclude must be a string`，退出码 2。其余五组读数与基线逐字相同。

套件结论：`pytest tests/test_schema.py tests/test_black.py tests/test_format.py` → **373 passed, 4 subtests passed**（与原仓库基线完全一致）。

### 拷贝 B：把 schema 里这两个键的 type 放宽（只改 JSON）

改法：`src/black/resources/black.schema.json` 中 `include` / `force-exclude` 的 `"type": "string"` 改为 `"type": ["string", "array"]`。

三组关键读数（与基线逐字相同，静默部分格式化照旧）：

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

套件结论：同样 **373 passed, 4 subtests passed**——全绿恰恰说明问题：`black.schema.json` 运行时根本没人读。它只被 validate-pyproject 类外部工具和编辑器消费，`test_schema` 也只断言 `line-length` 是 integer。**这条路根本没碰到运行时**：行为读数零变化，唯一"效果"是让编辑器/CI 的 schema 校验不再对错误配置标红，等于把 bug 合法化。

## 四、统一规则（建议）

四个键同为"正则字符串"键，规则应当一致：

- **校验内容**：四键（`exclude`、`extend-exclude`、`force-exclude`、`include`）在 `read_pyproject_toml` 一律要求 TOML 字符串；列表、表、整数等非字符串当场拒绝，一个文件都不处理。
- **报错文案**：`Config key <键名> must be a string`（键名用命令行写法，带连字符）。
- **退出码**：2（`click.BadOptionUsage` 属 UsageError，click 固定出口码 2，与命令行传错参同等待遇）。
- **已正确的两键**：`exclude` / `extend-exclude` 的现有文案**保留不动**，新补的两键复用同一句式，四键文案、行为、退出码完全对齐，用户只需记一条规则。
- **schema 侧**：`black.schema.json` 四键维持 `"type": "string"` 不放宽；schema 是运行前的第一道提示，运行时校验是最后一道，两层各就各位，而不是让前者迁就后者的漏洞。
