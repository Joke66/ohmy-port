namespace OhmyPort.Core;

/// <summary>应用元信息与外部地址。</summary>
public static class AppInfo
{
    public const string Name = "OhmyPort";
    public const string Version = "1.8.7";
    public const string Author = "ShineZhang";
    public const string Date = "2026-11-12";
    public const string Url = "https://gitee.com/Shine_Zhang/ohmy-port";
    public const string UpdateApi = "https://gitee.com/api/v5/repos/Shine_Zhang/ohmy-port/releases/latest";
    public const string UpdatePage = "https://gitee.com/Shine_Zhang/ohmy-port/releases";
}

/// <summary>串口默认值。</summary>
public static class SerialDefaults
{
    public static readonly string[] Bauds =
    [
        "115200", "57600", "38400", "19200", "9600", "4800", "2400", "921600",
    ];

    /// <summary>可选的文本编码（显示名 → Encoding 名）。</summary>
    public static readonly (string Label, string Key)[] Encodings =
    [
        ("UTF-8", "utf-8"),
        ("GBK", "gbk"),
        ("ASCII", "ascii"),
    ];

    /// <summary>发送时追加的换行符（显示名 → 实际字符）。</summary>
    public static readonly (string Label, string Value)[] Newlines =
    [
        ("无", ""),
        (@"\r", "\r"),
        (@"\n", "\n"),
        (@"\r\n", "\r\n"),
    ];
}

/// <summary>性能 / 行为参数，与 Python 版本保持一致。</summary>
public static class UiDefaults
{
    /// <summary>日志区最多保留行数。</summary>
    public const int MaxLines = 50_000;

    /// <summary>界面刷新间隔（毫秒）。</summary>
    public const int FlushMs = 80;

    /// <summary>串口单次读取字节数。</summary>
    public const int ReadChunk = 4096;

    /// <summary>关键词高亮重算间隔（秒）。</summary>
    public const double HighlightInterval = 0.5;

    /// <summary>端口热插拔检测间隔（毫秒）。</summary>
    public const int HotplugMs = 2000;

    /// <summary>绘图窗口保留的采样点数。</summary>
    public const int PlotWindow = 600;

    /// <summary>发送历史最多保留条数。</summary>
    public const int SendHistoryMax = 50;
}

/// <summary>日志保留策略：显示名 / 配置键 / 保留天数（0 表示无限制）。</summary>
public static class LogRetention
{
    public static readonly (string Label, string Key, int Days)[] Options =
    [
        ("一周", "week", 7),
        ("一个月", "month", 30),
        ("半年", "half_year", 180),
        ("一年", "year", 365),
        ("无限制", "unlimited", 0),
    ];

    public static readonly string[] Keys = [.. Options.Select(o => o.Key)];

    public static int DaysOf(string key) =>
        Options.FirstOrDefault(o => o.Key == key).Days;
}

/// <summary>主题标识。</summary>
public static class Themes
{
    public const string Auto = "auto";
    public const string Black = "black";
    public const string Eye = "eye";
    public const string Day = "day";

    public static readonly string[] All = [Auto, Black, Eye, Day];
}
