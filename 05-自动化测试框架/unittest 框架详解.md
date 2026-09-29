---
created: 2026-07-31
tags: [自动化测试框架/unittest]
---

# unittest 框架详解

![[assets/unittest-lifecycle.svg]]
*图示：unittest 三层前后置的嵌套顺序——模块级包类级、类级包用例级；每个 `test_` 方法都会新建一个 TestCase 实例，所以 `self` 上的状态无法跨用例传递。*

> Python 标准库自带的 xUnit 风格测试框架，pytest 出现前的事实标准，现在仍是「看懂老项目」和「理解 pytest 为什么这么设计」的必修课。

## 概念

### 出身：xUnit 家族的 Python 移植

`unittest` 是 JUnit 的 Python 移植（早期叫 PyUnit），所以它带着浓重的 Java 味：

- 必须**继承类** `unittest.TestCase`；
- 断言必须用**方法** `self.assertEqual(a, b)` 而不是 `assert`；
- 命名是 **camelCase**（`setUp` / `tearDown` / `assertEqual`），不符合 PEP 8 的 snake_case。

理解这三点，就理解了 pytest 之所以流行的全部动机——pytest 用「函数 + 原生 assert + fixture」把这三层样板全拆掉了。

### 五个核心概念

| 概念 | 作用 |
|------|------|
| `TestCase` | 测试用例的载体，一个类里的每个 `test_` 方法是一条用例 |
| `TestSuite` | 用例集合，可以嵌套，用来组织执行范围 |
| `TestLoader` | 从模块/目录中**发现**并加载用例，生成 TestSuite |
| `TestRunner` | 执行 Suite 并输出结果（`TextTestRunner` 是内置的命令行版） |
| `TestResult` | 承载执行结果：成功数、失败数、错误数、跳过数 |

这套「Loader 发现 → Suite 组织 → Runner 执行 → Result 收集」的四段式，是所有 xUnit 框架的通用架构。pytest 的收集树（Session → Module → Class → Function）本质上是同一套东西的更灵活版本。

### 生命周期：三层前后置

```python
import unittest


def setUpModule():
    """整个模块执行前一次。注意是模块级函数，不是方法。"""
    print("① setUpModule")


def tearDownModule():
    print("⑧ tearDownModule")


class TestDemo(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        """整个类执行前一次，必须是 classmethod。"""
        print("② setUpClass")

    @classmethod
    def tearDownClass(cls):
        print("⑦ tearDownClass")

    def setUp(self):
        """每个 test_ 方法执行前一次。"""
        print("  ③ setUp")

    def tearDown(self):
        """每个 test_ 方法执行后一次（即使用例失败也执行）。"""
        print("  ⑤ tearDown")

    def test_a(self):
        print("  ④ test_a")

    def test_b(self):
        print("  ⑥ test_b")
```

执行 `python -m unittest -s test_demo.py -v` 的输出顺序印证了嵌套结构：模块级最外，类级次之，用例级最内。

一个高频面试考点：**每个 `test_` 方法都会创建一个全新的 TestCase 实例**。

```python
class TestIsolation(unittest.TestCase):
    def test_1(self):
        self.value = 100          # 挂在实例上
        print(id(self))

    def test_2(self):
        print(id(self))            # id 不同，是另一个实例
        print(hasattr(self, "value"))   # False —— 拿不到 test_1 设的值
```

这是框架**刻意的隔离设计**：用例之间不应该有状态传递。要共享，只能通过 `setUpClass` 挂在 `cls` 上（类属性），或者用外部存储。

### 断言方法家族

| 方法 | 含义 | 备注 |
|------|------|------|
| `assertEqual(a, b)` | `a == b` | 失败信息会 diff，最常用 |
| `assertTrue(x)` / `assertFalse(x)` | 真值判断 | 别用它替代 assertEqual，失败信息只有 `False is not true` |
| `assertIs(a, b)` / `assertIsNot` | `a is b` | 判断同一对象 |
| `assertIsNone(x)` | `x is None` | |
| `assertIn(a, b)` | `a in b` | 子串、列表成员 |
| `assertAlmostEqual(a, b, places=7)` | 浮点近似相等 | 浮点比较必须用它 |
| `assertRaises(Exc)` | 断言抛异常 | 用作上下文管理器 |
| `assertRegex(s, r)` | 正则匹配 | |
| `assertCountEqual(a, b)` | 元素相同不管顺序 | 名字极具误导性，不是比长度 |
| `assertDictEqual` / `assertListEqual` | 类型 + 内容 | `assertEqual` 会自动分派到它们 |

```python
class TestAssertions(unittest.TestCase):

    def test_raises(self):
        with self.assertRaises(ZeroDivisionError):
            1 / 0

        # 还能校验异常信息
        with self.assertRaisesRegex(ValueError, r"invalid literal.*'abc'"):
            int("abc")

    def test_float(self):
        self.assertAlmostEqual(0.1 + 0.2, 0.3)        # 通过
        # self.assertEqual(0.1 + 0.2, 0.3)            # 失败：0.30000000000000004

    def test_unordered(self):
        self.assertCountEqual([1, 2, 2, 3], [3, 2, 1, 2])   # 通过，忽略顺序
```

### 跳过与预期失败

```python
import sys
import unittest


class TestSkip(unittest.TestCase):

    @unittest.skip("功能已下线")
    def test_deprecated(self):
        ...

    @unittest.skipIf(sys.platform == "win32", "该用例仅在 Linux 运行")
    def test_linux_only(self):
        ...

    @unittest.skipUnless(sys.version_info >= (3, 10), "需要 3.10+")
    def test_match_case(self):
        ...

    @unittest.expectedFailure
    def test_known_bug(self):
        """已知缺陷 JIRA-1234，修复前保持这个标记。"""
        self.assertEqual(1, 2)

    def test_runtime_skip(self):
        if not self._service_alive():
            self.skipTest("依赖服务未启动")   # 运行时动态跳过
```

## 用法

### 组织与执行：Suite / Loader / Runner

最常见的三种执行方式，从简到繁：

```bash
# 1. 命令行发现执行（推荐）：从当前目录递归找 test*.py
python -m unittest discover -s tests -p "test_*.py" -v

# 2. 精确执行到方法
python -m unittest tests.test_login.TestLogin.test_ok -v

# 3. 老项目常见的 main 入口
python test_login.py
```

手工组 Suite（老项目里到处都是，需要能看懂）：

```python
import unittest

from tests.test_login import TestLogin
from tests.test_order import TestOrder


def build_suite() -> unittest.TestSuite:
    suite = unittest.TestSuite()

    # 方式一：逐条加，能精确控制顺序
    suite.addTest(TestLogin("test_ok"))
    suite.addTest(TestLogin("test_wrong_password"))

    # 方式二：整个类加载
    loader = unittest.TestLoader()
    suite.addTests(loader.loadTestsFromTestCase(TestOrder))

    # 方式三：按目录发现
    suite.addTests(loader.discover(start_dir="tests/api", pattern="test_*.py"))
    return suite


if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(build_suite())
    raise SystemExit(0 if result.wasSuccessful() else 1)   # 给 CI 返回正确退出码
```

最后一行很关键：`TextTestRunner` **不会**自动设置进程退出码，直接跑脚本时失败也返回 0，CI 会误判为成功。这是老项目里非常常见的一个坑。

### addCleanup：比 tearDown 更可靠的清理

`tearDown` 的致命缺陷是：**如果 `setUp` 执行到一半抛异常，`tearDown` 不会被调用**，前半段已经创建的资源就泄漏了。

```python
class TestResource(unittest.TestCase):

    def setUp(self):
        self.conn = create_db_conn()
        self.addCleanup(self.conn.close)          # 注册即生效

        self.user = create_test_user()
        self.addCleanup(delete_user, self.user.id)   # 支持传参

        raise RuntimeError("模拟 setUp 后半段失败")
        # 即便这里炸了，上面注册的两个 cleanup 依然会被执行（LIFO 顺序）
```

`addCleanup` 的三个优势：

1. **注册即生效**，不依赖 `setUp` 是否跑完；
2. **LIFO 逆序执行**，与资源创建顺序天然匹配；
3. **就近声明**，创建和清理写在一起，不用在 `tearDown` 里再判断一遍 `hasattr`。

对应到 pytest，就是 fixture 的 `yield` 后置和 `request.addfinalizer`。

### 参数化：unittest 的最大短板

unittest 原生**不支持参数化**。三种绕法：

```python
# 方法一：subTest（Python 3.4+，标准库内置，推荐）
class TestSubTest(unittest.TestCase):
    def test_lengths(self):
        cases = [(5, False), (6, True), (20, True), (21, False)]
        for length, expected in cases:
            with self.subTest(length=length):      # 每个子用例独立报告
                self.assertEqual(is_valid_len(length), expected)
```

`subTest` 的好处是**一个子用例失败不会中断循环**，报告里会列出所有失败的子项：

```text
FAIL: test_lengths (TestSubTest) [length=6]
FAIL: test_lengths (TestSubTest) [length=21]
```

但它仍然算**一条**用例，无法单独执行某个子项，也无法单独打标记——这是它与 pytest `parametrize` 的本质差距。

```python
# 方法二：第三方库 parameterized
from parameterized import parameterized


class TestParam(unittest.TestCase):
    @parameterized.expand([
        ("下边界", 6, True),
        ("上边界", 20, True),
        ("离点", 21, False),
    ])
    def test_len(self, name, length, expected):
        self.assertEqual(is_valid_len(length), expected)


# 方法三：动态生成方法（老项目常见，可读性差，了解即可）
def _make_test(length, expected):
    def test(self):
        self.assertEqual(is_valid_len(length), expected)
    return test


for i, (ln, exp) in enumerate([(6, True), (21, False)]):
    setattr(TestParam, f"test_len_{i}", _make_test(ln, exp))
```

### 用 pytest 跑 unittest 用例

这是老项目迁移最实用的知识点：**pytest 能直接执行 unittest 风格的用例**，不用改一行代码。

```bash
pytest tests/ -v          # TestCase 子类会被正常收集执行
```

能用的：`setUp` / `tearDown` / `setUpClass` / `TestCase` 断言方法 / `skip` 系列 / `subTest`。

**不能用的**（这是迁移期最容易踩的坑）：

- unittest 的 `TestCase` 子类里**不能用 `@pytest.mark.parametrize`**（pytest 无法给它注入参数）；
- **不能把 fixture 作为方法参数注入**，只能用 `@pytest.fixture(autouse=True)` + `request.cls` 间接传值。

```python
import pytest
import unittest


@pytest.fixture(scope="class")
def db(request):
    conn = create_db_conn()
    request.cls.db = conn          # 通过 request.cls 挂到类上
    yield
    conn.close()


@pytest.mark.usefixtures("db")
class TestLegacy(unittest.TestCase):
    def test_query(self):
        assert self.db.query("select 1")   # 通过 self.db 拿到
```

迁移策略：**先让老用例在 pytest 下跑起来（零改动），新用例一律用 pytest 函数式写法，老用例按模块逐步重写**，不要一次性大改。

## 踩坑

1. **直接跑脚本时 CI 永远绿灯**。`unittest.TextTestRunner().run(suite)` 不设置退出码，`python run.py` 无论成败都返回 0。必须自己 `raise SystemExit(0 if result.wasSuccessful() else 1)`，或者干脆用 `python -m unittest`（它会正确设置退出码）。

2. **用例执行顺序是方法名 ASCII 排序，不是书写顺序**。`test_10_pay` 会排在 `test_2_login` **前面**（字符 `1 < 2`）。老项目常靠 `test_01_` / `test_02_` 前缀强行控序——这本身就是设计缺陷（用例有依赖），但接手时要知道命名不能乱改。

3. **`setUp` 中途失败导致资源泄漏**。`setUp` 里建了连接又建用户，建用户失败，`tearDown` 不会执行，连接泄漏。跑几百条后数据库连接被打满。解法就是全部改成 `addCleanup`。

4. **`assertTrue` 滥用导致失败信息毫无价值**。写 `self.assertTrue(resp.json()["code"] == 0)`，失败时只显示 `False is not true`，完全不知道实际值是多少。改成 `self.assertEqual(resp.json()["code"], 0)`，失败信息会告诉你实际是 `10001`。

5. **`assertCountEqual` 望文生义**。看名字以为是比较元素个数，实际是「忽略顺序比较元素是否相同」（Python 2 里叫 `assertItemsEqual`，改名后更误导了）。

6. **`setUpClass` 里的状态被后续用例污染**。类级 fixture 建的对象是共享的，某条用例改了它，后面的用例就跑在脏数据上，表现为「单独跑过、一起跑挂」。定位方法：`python -m unittest tests.test_x.TestX.test_y` 单跑对比。

7. **多个 TestCase 类同名方法互相干扰**。`loadTestsFromName` 用字符串定位用例，两个模块同名类会导致加载到错的那个。老项目里模块命名不规范时高发。

8. **`@unittest.skip` 的用例在报告里被忽视**。skip 数不进失败数，CI 也是绿的。跑了三个月才发现核心用例被人 skip 了却没人知道。**在 CI 里对 skip 数量设阈值告警**，或用 `-v` 输出并人工 review。

9. **迁移到 pytest 后 `parametrize` 静默不生效**。在 `TestCase` 子类上写 `@pytest.mark.parametrize`，pytest 会报错 `fixture 'x' not found` 或直接跳过。必须先把类改成普通类（去掉 `unittest.TestCase` 继承）才能用。

## 面试怎么答

**Q：unittest 和 pytest 有什么区别？**

A（30 秒骨架）：unittest 是标准库自带的 xUnit 风格框架，用例必须继承 `TestCase`、断言用 `assertEqual` 系列方法、前后置是 `setUp`/`tearDown`。pytest 是第三方框架，用例可以是普通函数、断言用原生 `assert`（靠 AST 重写给出详细失败信息）、前后置用 fixture。核心差距在三点：**参数化**（unittest 只有 subTest，粒度粗且不能单独执行）、**fixture 的组合与作用域**（unittest 只有固定的三层前后置，fixture 可以任意组合、依赖、指定四种作用域）、**插件生态**（xdist 并行、allure 报告、rerunfailures 重试）。工程上一般用 pytest 跑 unittest 的老用例做平滑迁移。

**追问 1：`setUp` 和 `setUpClass` 的区别？**

A：`setUp` 是实例方法，每个 `test_` 方法前都执行一次；`setUpClass` 是 `@classmethod`，整个类只执行一次。用途区分是「建得贵不贵、能不能共享」：数据库连接、浏览器实例这类昂贵资源放 `setUpClass`，每条用例都要求干净的测试数据放 `setUp`。要注意 `setUpClass` 里的状态是共享的，一条用例改了会污染后面的用例。对应 pytest 就是 `scope="class"` 和 `scope="function"`。

**追问 2：为什么每个 test 方法都新建实例？**

A：这是框架刻意做的用例隔离——保证 `self` 上的状态不会跨用例传递，避免用例之间隐式依赖。副作用是「想共享状态只能用类属性或外部存储」，这也是为什么 `setUpClass` 必须写成 classmethod。pytest 的函数式用例天然没有这个问题，共享靠 fixture 的 scope 显式声明，比隐式的类属性清晰得多。

**追问 3：`tearDown` 和 `addCleanup` 选哪个？**

A：优先 `addCleanup`。`tearDown` 有个致命缺陷：`setUp` 执行到一半抛异常时它不会被调用，前半段创建的资源就泄漏了。`addCleanup` 是注册即生效，无论后续是否异常都会按 LIFO 逆序执行，而且创建和清理代码写在一起，不用在 `tearDown` 里 `hasattr` 判断资源是否存在。我在实际项目里就因为 `setUp` 建连接后建用户失败，导致连接池被打满，改成 `addCleanup` 解决的。

**追问 4：老项目全是 unittest，怎么迁到 pytest？**

A：分三步，不做大爆炸式重写。第一步：直接用 `pytest tests/` 跑，unittest 用例零改动就能执行，先把执行入口统一，接上 allure 报告和 CI。第二步：新增用例一律用 pytest 函数式写法，两种风格共存没问题。第三步：按模块逐步重写老用例，优先重写那些「需要参数化」和「需要复杂前后置」的模块，因为它们从 fixture 和 parametrize 里获益最大。迁移期要注意 `TestCase` 子类里不能用 `parametrize`、不能直接注入 fixture，只能通过 `@pytest.mark.usefixtures` + `request.cls` 变通。

## 参考

- [unittest 官方文档](https://docs.python.org/zh-cn/3/library/unittest.html)
- [pytest 对 unittest 的支持](https://docs.pytest.org/en/stable/how-to/unittest.html)
- 相关笔记：[[pytest 用例发现规则]]、[[pytest fixture 详解]]、[[pytest 参数化 parametrize]]、[[pytest 断言重写机制]]
