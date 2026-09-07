"""核心纯逻辑单元测试（无需 GUI）。"""

import serial_tool as st


# ---------- LogFilter ----------
def test_parse_keywords():
    assert st.LogFilter.parse_keywords("Err,Timeout,0x50") == ["Err", "Timeout", "0x50"]
    assert st.LogFilter.parse_keywords("a  b c") == ["a", "b", "c"]
    assert st.LogFilter.parse_keywords("a,a,b") == ["a", "b"]
    assert st.LogFilter.parse_keywords("") == []


def test_matched_case_insensitive():
    f = st.LogFilter(keywords=["err"])
    assert f.matched("Error occurred") == ["err"]
    assert f.matched("no hit") == []


def test_matched_case_sensitive():
    f = st.LogFilter(keywords=["err"], case_sensitive=True)
    assert f.matched("err") == ["err"]
    assert f.matched("Error") == []


def test_visible_modes():
    kw = ["err"]
    inc = st.LogFilter(keywords=kw, mode="include")
    exc = st.LogFilter(keywords=kw, mode="exclude")
    hl = st.LogFilter(keywords=kw, mode="highlight")
    assert inc.visible("Error") is True
    assert inc.visible("ok") is False
    assert exc.visible("Error") is False
    assert exc.visible("ok") is True
    assert hl.visible("anything") is True


# ---------- PlotRule ----------
def test_plot_rule_regex():
    r = st.PlotRule("temp", r"temp=(\d+\.?\d*)")
    assert r.match("temp=36.5") == 36.5
    assert r.match("no") is None


def test_plot_rule_keyword():
    r = st.PlotRule("temp", "temp=")
    assert r.match("temp=36.5") == 36.5


# ---------- 辅助函数 ----------
def test_fmt_val():
    assert st._fmt_val(3.0) == "3"
    assert st._fmt_val(3.14) == "3.14"
    assert st._fmt_val(3.14159) == "3.1416"


def test_fmt_bytes():
    assert st._fmt_bytes(512) == "512 B"
    assert st._fmt_bytes(2048) == "2.0 KB"
    assert st._fmt_bytes(3 * 1024 * 1024) == "3.0 MB"


def test_extract_numbers():
    assert st._extract_numbers("temp=36.5") == [36.5]
    assert st._extract_numbers("a1 b2.5 c-3") == [1.0, 2.5, -3.0]


def test_parse_hex():
    assert st.SerialSession._parse_hex(None, "01 03 0A") == b"\x01\x03\x0a"
    assert st.SerialSession._parse_hex(None, "0x01 0xFF") == b"\x01\xff"
    assert st.SerialSession._parse_hex(None, "zz") is None


def test_parse_version():
    assert st._parse_version("OhmyPort_v1.2.0") == (1, 2, 0)
    assert st._parse_version("v1.10.0") == (1, 10, 0)
    assert st._parse_version("no version") == ()


# ---------- 配置导出/导入（命令页与命令） ----------
def test_load_pages_commands_roundtrip():
    data = {
        "pages": ["第1页", "测控", "调试"],
        "commands": [
            {"name": "查询温度", "content": "AA 55 01", "cycle": True, "page": 1},
            {"name": "重启", "content": "AA 55 02", "cycle": False, "page": 2},
        ],
    }
    pages, cmds = st._load_pages_commands(data, ["第1页"])
    assert pages == ["第1页", "测控", "调试"]
    assert len(cmds) == 2
    assert cmds[0]["name"] == "查询温度"
    assert cmds[0]["content"] == "AA 55 01"
    assert cmds[0]["cycle"] is True
    assert cmds[0]["page"] == 1
    assert cmds[1]["page"] == 2


def test_load_pages_commands_invalid_page_fallback():
    data = {
        "pages": ["第1页"],
        "commands": [{"name": "x", "content": "y", "page": 99}],
    }
    pages, cmds = st._load_pages_commands(data, ["第1页"])
    assert pages == ["第1页"]
    assert cmds[0]["page"] == 0  # 越界回退到第 1 页


def test_load_pages_commands_missing_pages_kept():
    data = {"commands": [{"name": "x", "content": "y", "page": 0}]}
    pages, cmds = st._load_pages_commands(data, ["第1页"])
    assert pages == ["第1页"]  # 无 pages 字段时保留默认页
    assert cmds[0]["page"] == 0


def test_load_pages_commands_skips_empty():
    data = {
        "pages": ["第1页"],
        "commands": [{"name": "", "content": "", "page": 0}, {"name": "ok", "content": "1", "page": 0}],
    }
    _, cmds = st._load_pages_commands(data, ["第1页"])
    assert len(cmds) == 1
    assert cmds[0]["name"] == "ok"
