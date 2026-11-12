using System.Globalization;
using System.Text.RegularExpressions;

namespace OhmyPort.Core.Models;

/// <summary>
/// 单条数值提取规则：正则（带捕获组）或关键词（取其后第一个数字）。
/// 对应 Python 版 plot_widget.PlotRule。
/// </summary>
public sealed class PlotRule
{
    private static readonly CultureInfo Inv = CultureInfo.InvariantCulture;

    private readonly Regex? _regex;

    public string Name { get; }
    public string Pattern { get; }

    public PlotRule(string name, string pattern)
    {
        Name = name;
        Pattern = pattern;
        try
        {
            var rx = new Regex(pattern);
            if (rx.GetGroupNumbers().Length > 1)
            {
                _regex = rx;
            }
        }
        catch (ArgumentException)
        {
            _regex = null;
        }
    }

    /// <summary>命中则返回数值，否则返回 null。</summary>
    public double? Match(string text)
    {
        if (_regex is not null)
        {
            var m = _regex.Match(text);
            if (!m.Success)
            {
                return null;
            }

            var g = m.Groups[1].Value;
            if (double.TryParse(g, NumberStyles.Float, Inv, out var v))
            {
                return v;
            }

            var nums = TextUtil.ExtractNumbers(m.Value);
            return nums.Count > 0 ? nums[0] : null;
        }

        if (Pattern.Length > 0)
        {
            var idx = text.IndexOf(Pattern, StringComparison.OrdinalIgnoreCase);
            if (idx >= 0)
            {
                var nums = TextUtil.ExtractNumbers(text[(idx + Pattern.Length)..]);
                return nums.Count > 0 ? nums[0] : null;
            }
        }

        return null;
    }
}
