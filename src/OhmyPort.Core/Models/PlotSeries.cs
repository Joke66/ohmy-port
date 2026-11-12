namespace OhmyPort.Core.Models;

/// <summary>一条曲线定义（持久化用）：名称 + 提取规则。</summary>
public sealed class PlotRuleConfig
{
    public string Name { get; set; } = "";
    public string Pattern { get; set; } = "";

    public PlotRuleConfig() { }

    public PlotRuleConfig(string name, string pattern)
    {
        Name = name;
        Pattern = pattern;
    }
}

/// <summary>
/// 一条曲线的采样缓冲：定长环形队列，按「逻辑索引 0 = 最旧」读取。
/// 缺失值以 <see cref="double.NaN"/> 表示，绘制时断线。
/// </summary>
/// <remarks>非线程安全：只在 UI 线程读写。</remarks>
public sealed class PlotSeries
{
    private readonly double[] _values;
    private int _head;
    private int _count;

    public PlotSeries(string name, int capacity)
    {
        Name = name;
        _values = new double[Math.Max(2, capacity)];
    }

    public string Name { get; }

    public int Capacity => _values.Length;

    /// <summary>当前有效采样点数（未填满时小于 Capacity）。</summary>
    public int Count => _count;

    /// <summary>逻辑索引 0 为最旧的一个点。</summary>
    public double this[int index]
    {
        get
        {
            var start = _count == _values.Length ? _head : 0;
            return _values[(start + index) % _values.Length];
        }
    }

    public void Add(double value)
    {
        _values[_head] = value;
        _head = (_head + 1) % _values.Length;
        if (_count < _values.Length)
        {
            _count++;
        }
    }

    public void Clear()
    {
        _head = 0;
        _count = 0;
    }

    /// <summary>窗口内的最小/最大值（忽略 NaN）；没有有效点时返回 null。</summary>
    public (double Min, double Max)? Range()
    {
        var min = double.MaxValue;
        var max = double.MinValue;
        var any = false;
        for (var i = 0; i < _count; i++)
        {
            var v = this[i];
            if (double.IsNaN(v) || double.IsInfinity(v))
            {
                continue;
            }

            any = true;
            if (v < min)
            {
                min = v;
            }

            if (v > max)
            {
                max = v;
            }
        }

        return any ? (min, max) : null;
    }

    /// <summary>最近一个有效采样值。</summary>
    public double? Latest
    {
        get
        {
            for (var i = _count - 1; i >= 0; i--)
            {
                var v = this[i];
                if (!double.IsNaN(v) && !double.IsInfinity(v))
                {
                    return v;
                }
            }

            return null;
        }
    }
}

/// <summary>
/// 一个会话的曲线数据集合：按规则从日志行提取数值，追加到对应曲线缓冲。
/// 供界面层定时重绘（本类只负责数据，不含绘制）。
/// </summary>
/// <remarks>非线程安全：<see cref="Feed"/> 与绘制都要在 UI 线程调用。</remarks>
public sealed class PlotHub
{
    private readonly List<PlotRule> _rules = [];
    private readonly List<PlotSeries> _series = [];

    /// <summary>每条曲线保留的采样点数。</summary>
    public int Capacity { get; private set; } = UiDefaults.PlotWindow;

    public IReadOnlyList<PlotSeries> Series => _series;

    /// <summary>是否已配置曲线（没配时不需要采集，也不显示窗口内容）。</summary>
    public bool Enabled => _rules.Count > 0;

    /// <summary>
    /// 重配曲线：同名曲线沿用已有缓冲（容量不变时），其余重建。
    /// </summary>
    public void Configure(IEnumerable<PlotRuleConfig>? rules, int capacity)
    {
        capacity = Math.Max(2, capacity);
        var valid = (rules ?? [])
            .Where(r => r is not null && r.Name.Length > 0 && r.Pattern.Length > 0)
            .ToList();

        var newSeries = new List<PlotSeries>(valid.Count);
        var newRules = new List<PlotRule>(valid.Count);
        foreach (var cfg in valid)
        {
            var existing = _series.FirstOrDefault(s => s.Name == cfg.Name);
            newSeries.Add(existing is not null && existing.Capacity == capacity
                ? existing
                : new PlotSeries(cfg.Name, capacity));
            newRules.Add(new PlotRule(cfg.Name, cfg.Pattern));
        }

        _rules.Clear();
        _rules.AddRange(newRules);
        _series.Clear();
        _series.AddRange(newSeries);
        Capacity = capacity;
    }

    /// <summary>喂入一行文本：每条规则各取一个值（取不到记 NaN 形成断点）。</summary>
    public void Feed(string? text)
    {
        if (_rules.Count == 0 || string.IsNullOrEmpty(text))
        {
            return;
        }

        for (var i = 0; i < _rules.Count; i++)
        {
            _series[i].Add(_rules[i].Match(text!) ?? double.NaN);
        }
    }

    public void Clear()
    {
        foreach (var s in _series)
        {
            s.Clear();
        }
    }

    /// <summary>改容量（界面「点数」下拉），已有数据按新容量重建。</summary>
    public void SetCapacity(int capacity)
    {
        capacity = Math.Max(2, capacity);
        if (capacity == Capacity)
        {
            return;
        }

        for (var i = 0; i < _series.Count; i++)
        {
            var old = _series[i];
            var fresh = new PlotSeries(old.Name, capacity);
            // 尽量保留最近的点
            var keep = Math.Min(old.Count, capacity);
            for (var k = old.Count - keep; k < old.Count; k++)
            {
                fresh.Add(old[k]);
            }

            _series[i] = fresh;
        }

        Capacity = capacity;
    }
}
