namespace OhmyPort.Core;

/// <summary>过滤模式。</summary>
public static class FilterModes
{
    public const string Highlight = "highlight";
    public const string Include = "include";
    public const string Exclude = "exclude";
    public const string Split = "split";
}

/// <summary>多关键词过滤 / 高亮（对应 Python 版 common.LogFilter）。</summary>
public sealed class LogFilter
{
    public IReadOnlyList<string> Keywords { get; }
    public string Mode { get; }
    public bool CaseSensitive { get; }

    public LogFilter(IEnumerable<string>? keywords = null, string mode = FilterModes.Highlight,
                     bool caseSensitive = false)
    {
        Keywords = (keywords ?? []).Where(k => !string.IsNullOrEmpty(k)).ToArray();
        Mode = mode;
        CaseSensitive = caseSensitive;
    }

    /// <summary>把 ",;空白换行" 统一成分隔符后去重解析。</summary>
    public static List<string> ParseKeywords(string? text)
    {
        text ??= "";
        foreach (var sep in new[] { ",", ";", "\n", "\t", " " })
        {
            text = text.Replace(sep, ",", StringComparison.Ordinal);
        }

        var seen = new List<string>();
        foreach (var raw in text.Split(','))
        {
            var k = raw.Trim();
            if (k.Length > 0 && !seen.Contains(k))
            {
                seen.Add(k);
            }
        }

        return seen;
    }

    /// <summary>返回命中的关键词（保持配置顺序）。</summary>
    public List<string> Matched(string line)
    {
        var hay = CaseSensitive ? line : line.ToLowerInvariant();
        var hits = new List<string>();
        foreach (var k in Keywords)
        {
            var needle = CaseSensitive ? k : k.ToLowerInvariant();
            if (needle.Length > 0 && hay.Contains(needle, StringComparison.Ordinal))
            {
                hits.Add(k);
            }
        }

        return hits;
    }

    /// <summary>该行是否应显示在主导出区。</summary>
    public bool Visible(string line)
    {
        if (Keywords.Count == 0)
        {
            return true;
        }

        var hit = Matched(line).Count > 0;
        return Mode switch
        {
            FilterModes.Include => hit,
            FilterModes.Exclude => !hit,
            _ => true,
        };
    }

    /// <summary>该模式是否需要高亮命中关键词。</summary>
    public bool HighlightEnabled => Mode is FilterModes.Highlight or FilterModes.Include or FilterModes.Split;
}
