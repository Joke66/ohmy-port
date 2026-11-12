using System.Text.Json;
using System.Text.Json.Serialization;

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
