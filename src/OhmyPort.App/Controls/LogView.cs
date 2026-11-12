using System.Text;
using System.Windows;
using System.Windows.Input;
using System.Windows.Media;
using ICSharpCode.AvalonEdit;
using ICSharpCode.AvalonEdit.Document;
using ICSharpCode.AvalonEdit.Editing;
using ICSharpCode.AvalonEdit.Rendering;
using ICSharpCode.AvalonEdit.Search;

namespace OhmyPort.App.Controls;

/// <summary>
/// 日志显示控件：基于 AvalonEdit 的虚拟化文本视图。
/// 负责批量追加、行数上限裁剪、自动滚底与按行着色（时间戳 / 发送 / 系统 / 关键词高亮）。
/// </summary>
public sealed class LogView : TextEditor
{
    /// <summary>发送方向标记（与 Python 版 _dir_mark 保持一致）。</summary>
    public const string TxMark = "SEND >>>>>>>>>>";

    /// <summary>系统消息标记。</summary>
    public const string SysMark = "◆ ";

    /// <summary>应答（发送后收到的第一条）标记。</summary>
    public const string ResponseMark = "RECV <<<<<<<<<<";

    private readonly LogColorizer _colorizer = new();

    public LogView()
    {
        IsReadOnly = true;
        ShowLineNumbers = false;
        WordWrap = true;
        FontFamily = new FontFamily("Consolas");
        FontSize = 12;
        Padding = new Thickness(6, 4, 6, 4);
        HorizontalScrollBarVisibility = System.Windows.Controls.ScrollBarVisibility.Disabled;
        VerticalScrollBarVisibility = System.Windows.Controls.ScrollBarVisibility.Auto;
        Options.EnableHyperlinks = false;
        Options.EnableEmailHyperlinks = false;
        Options.EnableRectangularSelection = false;
        Options.CutCopyWholeLine = false;
        Document.UndoStack.SizeLimit = 0;
        TextArea.TextView.LineTransformers.Add(_colorizer);
        SyntaxHighlighting = null;

        // 内置查找面板：Ctrl+F 打开、F3 下一个、Shift+F3 上一个、Esc 关闭
        SearchPanel.Install(this);

        // Ctrl+滚轮缩放字体（与 Python 版一致）
        PreviewMouseWheel += OnPreviewMouseWheel;

        // 立即应用主题底/前景/光标色，避免 new 出来到 ApplyThemeColors 之间闪白
        Loaded += (_, _) => ApplyTheme();
    }

    /// <summary>默认字号（与 Python 版 _DEFAULT_FONT_SIZE=11 对应，WPF 用 12 更接近视觉）。</summary>
    public const double DefaultFontSize = 12;

    private void OnPreviewMouseWheel(object sender, MouseWheelEventArgs e)
    {
        if ((Keyboard.Modifiers & ModifierKeys.Control) == 0)
        {
            return;
        }

        if (e.Delta > 0)
        {
            ZoomIn();
        }
        else
        {
            ZoomOut();
        }

        e.Handled = true;
    }

    public void ZoomIn(int step = 1) => FontSize = Math.Min(FontSize + step, 72);

    public void ZoomOut(int step = 1) => FontSize = Math.Max(FontSize - step, 6);

    public void ResetZoom() => FontSize = DefaultFontSize;

    /// <summary>最多保留的行数，超出从头部丢弃。</summary>
    public int MaxLines { get; set; } = 50_000;

    public Brush TimestampBrush
    {
        get => _colorizer.TimestampBrush;
        set => _colorizer.TimestampBrush = value;
    }

    public Brush TxBrush
    {
        get => _colorizer.TxBrush;
        set => _colorizer.TxBrush = value;
    }

    public Brush SysBrush
    {
        get => _colorizer.SysBrush;
        set => _colorizer.SysBrush = value;
    }

    public Brush ResponseBrush
    {
        get => _colorizer.ResponseBrush;
        set => _colorizer.ResponseBrush = value;
    }

    public Brush HighlightBackground
    {
        get => _colorizer.HighlightBackground;
        set => _colorizer.HighlightBackground = value;
    }

    public Brush HighlightForeground
    {
        get => _colorizer.HighlightForeground;
        set => _colorizer.HighlightForeground = value;
    }

    /// <summary>是否已停在最底部（用于决定是否自动跟随）。</summary>
    public bool IsAtBottom =>
        TextArea.TextView.ScrollOffset.Y + TextArea.TextView.ActualHeight >=
        TextArea.TextView.DocumentHeight - 4;

    /// <summary>批量追加若干行（每行自动补换行）。</summary>
    public void AppendLines(IReadOnlyList<string> lines, bool follow)
    {
        if (lines.Count == 0)
        {
            return;
        }

        var sb = new StringBuilder(lines.Count * 40);
        foreach (var line in lines)
        {
            sb.Append(line).Append('\n');
        }

        Document.BeginUpdate();
        try
        {
            Document.Insert(Document.TextLength, sb.ToString());
        }
        finally
        {
            Document.EndUpdate();
        }

        TrimToMaxLines();

        if (follow)
        {
            ScrollToEnd();
        }
    }

    /// <summary>
    /// 按当前主题刷新日志区外观。AvalonEdit 不参与全局控件样式表（它的默认样式是白底黑字），
    /// 背景 / 前景 / 光标 / 选区都必须显式设置，否则深色主题下会出现白底白字。
    /// </summary>
    public void ApplyTheme()
    {
        // 背景由外层 Border 用 Brush.LogSurface 画（背景皮肤开启时是半透明的），
        // 编辑器自身保持透明，否则会把背景图完全盖住。
        Background = Brushes.Transparent;
        SetResourceReference(ForegroundProperty, "Brush.Foreground");
        TextArea.SetResourceReference(TextArea.SelectionBrushProperty, "Brush.Accent");
        TextArea.SetResourceReference(TextArea.SelectionForegroundProperty, "Brush.AccentForeground");
        TextArea.Caret.CaretBrush = TryFindResource("Brush.Foreground") as Brush;
    }

    /// <summary>清空显示区（不影响调用方缓存的原始记录）。</summary>
    public void ClearAll() => Document.Text = "";

    /// <summary>关键词或着色规则变化后重绘可见区域。</summary>
    public void RefreshHighlight()
    {
        TextArea.TextView.Redraw();
    }

    public void SetKeywords(IReadOnlyList<string> keywords, bool caseSensitive)
    {
        _colorizer.Keywords = keywords;
        _colorizer.CaseSensitive = caseSensitive;
        TextArea.TextView.Redraw();
    }

    public string AllText => Document.Text;

    private void TrimToMaxLines()
    {
        var excess = Document.LineCount - MaxLines;
        if (excess <= 0)
        {
            return;
        }

        // 多留 1 行缓冲，避免每追加一行就删一次
        var firstKept = Document.GetLineByNumber(excess + 1);
        Document.Remove(0, firstKept.Offset);
    }
}

/// <summary>
/// 按行内容着色的转换器：无状态，只依赖行文本，因此滚动 / 重绘 / 重新载入都能正确显示。
/// 行格式：[时间戳] [方向标记]正文
/// </summary>
internal sealed class LogColorizer : DocumentColorizingTransformer
{
    public Brush TimestampBrush { get; set; } = Brushes.Gray;
    public Brush TxBrush { get; set; } = Brushes.DeepSkyBlue;
    public Brush SysBrush { get; set; } = Brushes.Gray;
    public Brush ResponseBrush { get; set; } = Brushes.LimeGreen;
    public Brush HighlightBackground { get; set; } = Brushes.DarkGoldenrod;
    public Brush HighlightForeground { get; set; } = Brushes.White;
    public IReadOnlyList<string> Keywords { get; set; } = [];
    public bool CaseSensitive { get; set; }

    protected override void ColorizeLine(DocumentLine line)
    {
        var text = CurrentContext.Document.GetText(line);
        if (text.Length == 0)
        {
            return;
        }

        var lineStart = line.Offset;
        var bodyIndex = 0;

        // 时间戳 "[HH:mm:ss.fff] "
        if (text[0] == '[')
        {
            var close = text.IndexOf(']');
            if (close > 0 && close + 1 < text.Length && text[close + 1] == ' ')
            {
                var tsEnd = close + 2;
                ChangeLinePart(lineStart, lineStart + tsEnd,
                               e => e.TextRunProperties.SetForegroundBrush(TimestampBrush));
                bodyIndex = tsEnd;
            }
        }

        var bodyBrush = BrushForMark(text, bodyIndex);
        if (bodyBrush is not null)
        {
            ChangeLinePart(lineStart + bodyIndex, lineStart + text.Length,
                           e => e.TextRunProperties.SetForegroundBrush(bodyBrush));
        }

        HighlightKeywords(text, lineStart, bodyIndex);
    }

    private Brush? BrushForMark(string text, int bodyIndex)
    {
        if (bodyIndex >= text.Length)
        {
            return null;
        }

        if (text.AsSpan(bodyIndex).StartsWith(LogView.TxMark, StringComparison.Ordinal))
        {
            return TxBrush;
        }

        if (text.AsSpan(bodyIndex).StartsWith(LogView.SysMark, StringComparison.Ordinal))
        {
            return SysBrush;
        }

        if (text.AsSpan(bodyIndex).StartsWith(LogView.ResponseMark, StringComparison.Ordinal))
        {
            return ResponseBrush;
        }

        return null;
    }

    private void HighlightKeywords(string text, int lineStart, int bodyIndex)
    {
        if (Keywords.Count == 0 || bodyIndex >= text.Length)
        {
            return;
        }

        var comparison = CaseSensitive ? StringComparison.Ordinal : StringComparison.OrdinalIgnoreCase;
        foreach (var keyword in Keywords)
        {
            if (keyword.Length == 0)
            {
                continue;
            }

            var index = bodyIndex;
            while (index < text.Length)
            {
                var hit = text.IndexOf(keyword, index, comparison);
                if (hit < 0)
                {
                    break;
                }

                var from = lineStart + hit;
                var to = from + keyword.Length;
                ChangeLinePart(from, to, e =>
                {
                    e.TextRunProperties.SetBackgroundBrush(HighlightBackground);
                    e.TextRunProperties.SetForegroundBrush(HighlightForeground);
                });
                index = hit + keyword.Length;
            }
        }
    }
}
