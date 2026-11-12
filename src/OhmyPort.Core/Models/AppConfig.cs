using System.Text.Json;
using System.Text.Json.Serialization;
using OhmyPort.Core.Serial;

namespace OhmyPort.Core.Models;

/// <summary>单个会话（串口标签页）的持久化状态。</summary>
public sealed class SessionConfig
{
    [JsonConverter(typeof(FlexibleStringConverter))]
    public string? Port { get; set; }

    [JsonConverter(typeof(FlexibleStringConverter))]
    public string? Baud { get; set; }

    public List<string> CustomBauds { get; set; } = [];

    public string FilterKeywords { get; set; } = "";
    public string FilterMode { get; set; } = FilterModes.Highlight;
    public bool FilterCase { get; set; }
    public bool FilterEnabled { get; set; }
    public int FontSize { get; set; } = 11;

    /// <summary>发送自动追加的校验类型（none/sum8/xor8/crc16_modbus）。</summary>
    public string SendChecksum { get; set; } = ChecksumKeys.None;

    /// <summary>协议帧解析设置（按帧切分接收流）。</summary>
    public bool FrameEnabled { get; set; }
    public string FrameHeader { get; set; } = "";
    public string FrameTail { get; set; } = "";
    public int FrameLengthSize { get; set; }
    public int FrameLengthBase { get; set; }
    public bool FrameBigEndian { get; set; } = true;
    public string FrameChecksum { get; set; } = ChecksumKeys.None;

    /// <summary>协议字段定义（按帧解析时把数据区解成结构化表格）。</summary>
    public List<ProtocolField> ProtocolFields { get; set; } = [];
}

/// <summary>
/// 应用配置。字段名与旧版（Python）的 serial_tool_config.json 完全一致（snake_case），
/// 因此老用户的配置可以直接沿用。
/// </summary>
public sealed class AppConfig
{
    public string Theme { get; set; } = Themes.Auto;

    public List<string> Pages { get; set; } = ["第1页"];

    public List<CommandItem> Commands { get; set; } = [];

    public bool AutoRecord { get; set; } = true;
    public int ShardMb { get; set; } = 5;
    public string LogRetention { get; set; } = "month";
    public string LastUpdateCheck { get; set; } = "";
    public string FontFamily { get; set; } = "Consolas";
    public bool WrapEnabled { get; set; } = true;
    public string CloseBehavior { get; set; } = "exit";
    public bool CloseConfirm { get; set; } = true;
    public string? LogDir { get; set; }

    public string BgDir { get; set; } = "";
    public string BgImage { get; set; } = "";
    public int BgBlur { get; set; } = 10;

    /// <summary>背景遮罩浓度（0-100%）：0 = 背景图完全可见，100 = 背景图几乎被窗口底色盖住。</summary>
    public int BgVeil { get; set; }

    public bool BgEnabled { get; set; }

    public List<SessionConfig> Sessions { get; set; } = [];

    public static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        WriteIndented = true,
        Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
        ReadCommentHandling = JsonCommentHandling.Skip,
        AllowTrailingCommas = true,
    };

    /// <summary>把外部来源的配置裁剪到合法范围（对应 Python 版 _load_config 的逐项校验）。</summary>
    public void Normalize()
    {
        Pages ??= ["第1页"];
        Commands ??= [];
        Sessions ??= [];

        if (!Themes.All.Contains(Theme))
        {
            Theme = Themes.Auto;
        }

        if (Pages.Count == 0)
        {
            Pages = ["第1页"];
        }

        if (ShardMb < 1)
        {
            ShardMb = 1;
        }

        if (!OhmyPort.Core.LogRetention.Keys.Contains(LogRetention))
        {
            LogRetention = "month";
        }

        if (CloseBehavior is not ("exit" or "tray"))
        {
            CloseBehavior = "exit";
        }

        BgBlur = Math.Clamp(BgBlur, 0, 50);
        BgVeil = Math.Clamp(BgVeil, 0, 100);

        if (string.IsNullOrEmpty(FontFamily))
        {
            FontFamily = "Consolas";
        }

        (Pages, Commands) = CommandPages.Load(Pages, Commands, ["第1页"]);

        Sessions = Sessions.Where(s => s is not null).ToList();
        foreach (var s in Sessions)
        {
            if (!AllFilterModes.Contains(s.FilterMode))
            {
                s.FilterMode = FilterModes.Highlight;
            }

            if (s.FontSize <= 0)
            {
                s.FontSize = 11;
            }

            if (!ChecksumKeys.All.Contains(s.SendChecksum))
            {
                s.SendChecksum = ChecksumKeys.None;
            }

            if (!ChecksumKeys.All.Contains(s.FrameChecksum))
            {
                s.FrameChecksum = ChecksumKeys.None;
            }

            if (s.FrameLengthSize is not (0 or 1 or 2 or 4))
            {
                s.FrameLengthSize = 0;
            }

            s.FrameLengthBase = Math.Clamp(s.FrameLengthBase, -65536, 65536);
            s.FrameHeader ??= "";
            s.FrameTail ??= "";

            s.ProtocolFields ??= [];
            s.ProtocolFields = s.ProtocolFields
                .Where(f => f is not null)
                .Select(f =>
                {
                    f.Type = FieldTypes.IsValid(f.Type) ? f.Type : FieldTypes.UInt8;
                    f.Name ??= "";
                    f.Offset = Math.Clamp(f.Offset, 0, 65535);
                    f.Length = Math.Clamp(f.Length, 1, 4096);
                    if (double.IsNaN(f.Scale) || double.IsInfinity(f.Scale))
                    {
                        f.Scale = 1;
                    }

                    if (double.IsNaN(f.Bias) || double.IsInfinity(f.Bias))
                    {
                        f.Bias = 0;
                    }

                    return f;
                })
                .ToList();

            s.CustomBauds ??= [];
            s.Port = string.IsNullOrEmpty(s.Port) ? null : s.Port;
            s.Baud = string.IsNullOrEmpty(s.Baud) ? null : s.Baud;
        }
    }

    private static readonly string[] AllFilterModes =
        [FilterModes.Highlight, FilterModes.Include, FilterModes.Exclude, FilterModes.Split];
}

/// <summary>兼容旧配置里 baud 既可能是字符串也可能是数字的写法。</summary>
public sealed class FlexibleStringConverter : JsonConverter<string?>
{
    public override string? Read(ref Utf8JsonReader reader, Type typeToConvert, JsonSerializerOptions options) =>
        reader.TokenType switch
        {
            JsonTokenType.String => reader.GetString(),
            JsonTokenType.Number => reader.TryGetInt64(out var l)
                ? l.ToString(System.Globalization.CultureInfo.InvariantCulture)
                : reader.GetDouble().ToString(System.Globalization.CultureInfo.InvariantCulture),
            JsonTokenType.Null => null,
            _ => Skip(reader),
        };

    public override void Write(Utf8JsonWriter writer, string? value, JsonSerializerOptions options)
    {
        if (value is null)
        {
            writer.WriteNullValue();
        }
        else
        {
            writer.WriteStringValue(value);
        }
    }

    private static string? Skip(Utf8JsonReader reader)
    {
        reader.Skip();
        return null;
    }
}
