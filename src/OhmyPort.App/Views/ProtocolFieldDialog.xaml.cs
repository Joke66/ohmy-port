using System.Collections.ObjectModel;
using System.Globalization;
using System.Windows;
using System.Windows.Controls;
using OhmyPort.Core.Models;

namespace OhmyPort.App.Views;

/// <summary>
/// 协议字段编辑对话框：一行一个字段（名称 / 偏移 / 类型 / 长度 / 字节序 / 系数 / 偏移量）。
/// 直接改文本框即可，点「确定」时统一校验并回写。
/// </summary>
public partial class ProtocolFieldDialog : Window
{
    private static readonly CultureInfo Inv = CultureInfo.InvariantCulture;

    private readonly ObservableCollection<FieldRow> _rows = [];

    public ProtocolFieldDialog(IEnumerable<ProtocolField> fields)
    {
        InitializeComponent();
        foreach (var f in fields)
        {
            _rows.Add(new FieldRow(f));
        }

        FieldList.ItemsSource = _rows;

        // 第一次打开且没有任何字段时，给一行空模板方便直接填
        if (_rows.Count == 0)
        {
            AddRow();
        }
    }

    /// <summary>校验通过后的字段列表。</summary>
    public List<ProtocolField> Result { get; private set; } = [];

    private void OnAddRowClick(object sender, RoutedEventArgs e) => AddRow();

    private void OnDeleteRowClick(object sender, RoutedEventArgs e)
    {
        if (sender is FrameworkElement { Tag: FieldRow row })
        {
            _rows.Remove(row);
        }
    }

    private void AddRow() =>
        _rows.Add(new FieldRow(new ProtocolField
        {
            Name = $"字段{_rows.Count + 1}",
            Offset = _rows.Count * 2,
        }));

    private void OnOkClick(object sender, RoutedEventArgs e)
    {
        var result = new List<ProtocolField>();
        for (var i = 0; i < _rows.Count; i++)
        {
            var row = _rows[i];
            var name = row.Name.Trim();
            if (name.Length == 0)
            {
                // 全空行直接忽略（用户可能只是留了一行没删）
                if (row.OffsetText.Trim().Length == 0 && row.LengthText.Trim().Length == 0)
                {
                    continue;
                }

                ShowError($"第 {i + 1} 行：名称不能为空。");
                return;
            }

            if (!int.TryParse(row.OffsetText.Trim(), out var offset) || offset < 0)
            {
                ShowError($"第 {i + 1} 行「{name}」：偏移必须是非负整数。");
                return;
            }

            var length = 1;
            if (row.LengthText.Trim().Length > 0 &&
                (!int.TryParse(row.LengthText.Trim(), out length) || length < 1))
            {
                ShowError($"第 {i + 1} 行「{name}」：长度必须是正整数。");
                return;
            }

            if (!double.TryParse(row.ScaleText.Trim(), NumberStyles.Float, Inv, out var scale))
            {
                ShowError($"第 {i + 1} 行「{name}」：系数无效。");
                return;
            }

            if (!double.TryParse(row.BiasText.Trim(), NumberStyles.Float, Inv, out var bias))
            {
                ShowError($"第 {i + 1} 行「{name}」：偏移量无效。");
                return;
            }

            result.Add(new ProtocolField
            {
                Name = name,
                Offset = offset,
                Type = FieldTypes.IsValid(row.TypeKey) ? row.TypeKey : FieldTypes.UInt8,
                BigEndian = row.BigEndian,
                Length = length,
                Scale = scale,
                Bias = bias,
            });
        }

        Result = result;
        DialogResult = true;
    }

    private void OnCancelClick(object sender, RoutedEventArgs e) => DialogResult = false;

    private void ShowError(string message) =>
        MessageBox.Show(this, message, "字段设置有误", MessageBoxButton.OK, MessageBoxImage.Warning);
}

/// <summary>一行字段的编辑态（文本形式保存输入，确定时再统一解析）。</summary>
public sealed class FieldRow
{
    public FieldRow(ProtocolField field)
    {
        Name = field.Name;
        OffsetText = field.Offset.ToString(CultureInfo.InvariantCulture);
        TypeKey = FieldTypes.IsValid(field.Type) ? field.Type : FieldTypes.UInt8;
        LengthText = field.Length.ToString(CultureInfo.InvariantCulture);
        BigEndian = field.BigEndian;
        ScaleText = field.Scale.ToString("0.####", CultureInfo.InvariantCulture);
        BiasText = field.Bias.ToString("0.####", CultureInfo.InvariantCulture);
    }

    public string Name { get; set; }

    public string OffsetText { get; set; }

    public string TypeKey { get; set; }

    public string LengthText { get; set; }

    public bool BigEndian { get; set; }

    public string ScaleText { get; set; }

    public string BiasText { get; set; }

    public IReadOnlyList<(string Label, string Key)> TypeOptions => Types;

    private static readonly (string Label, string Key)[] Types =
        FieldTypes.All.Select(t => (t.Label, t.Key)).ToArray();
}
