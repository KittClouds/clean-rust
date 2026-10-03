//+------------------------------------------------------------------+
//| OBS-OPEN-INST-01 V2.00/V2.10 indicator capture harness          |
//+------------------------------------------------------------------+
#property strict
#property indicator_chart_window
#property indicator_buffers 1
#property indicator_plots 1
#property indicator_type1 DRAW_NONE

double g_probe_buffer[];

input group "Capture"
input string InpV200Name = "OpeningRangeGrammar_v2_00_LegacyStateMachine";
input string InpV210Name = "OpeningRangeGrammar_v2_10_ExtremeSentinels";
input string InpOutputFile = "OBS_OPEN_INST01_capture.tsv";
input int InpCaptureMode = 0; // 0 online, 1 historical reload
input int InpMaxHistoricalBars = 5000;
input bool InpCaptureSentinelChanges = true;

input group "Legacy Breakout Clock"
input uint InpHourBegin = 9;
input uint InpMinBegin = 30;
input uint InpHourEnd = 9;
input uint InpMinEnd = 35;
input uint InpHourEndArea = 9;
input uint InpMinEndArea = 40;

int g_v200 = INVALID_HANDLE;
int g_v210 = INVALID_HANDLE;
int g_file = INVALID_HANDLE;
datetime g_last_bar = 0;
bool g_dumped = false;
double g_last_live_upper = EMPTY_VALUE;
double g_last_live_lower = EMPTY_VALUE;

string Cell(const double value)
{
   if(value == EMPTY_VALUE || !MathIsValidNumber(value))
      return "NA";
   return DoubleToString(value, 12);
}

string TimeCell(const datetime value)
{
   return value <= 0 ? "NA" : IntegerToString((long)value);
}

void Add(string &row, const string value)
{
   if(StringLen(row) > 0)
      StringAdd(row, "\t");
   StringAdd(row, value);
}

bool ReadOne(const int handle, const int buffer, const int shift, double &value)
{
   double values[1];
   ArrayInitialize(values, EMPTY_VALUE);
   if(handle == INVALID_HANDLE || CopyBuffer(handle, buffer, shift, 1, values) != 1)
   {
      value = EMPTY_VALUE;
      return false;
   }
   value = values[0];
   return true;
}

bool ReadAll(const int handle, const int buffer, const int count, double &values[])
{
   ArrayResize(values, count);
   ArrayInitialize(values, EMPTY_VALUE);
   return handle != INVALID_HANDLE && CopyBuffer(handle, buffer, 0, count, values) == count;
}

void WriteLine(const string row)
{
   FileWriteString(g_file, row + "\r\n");
}

void WriteHeader()
{
   string row = "";
   const string fixed[] = {"capture_mode", "event_kind", "symbol", "timeframe", "tick_time", "bar_open", "shift", "bar_high", "bar_low", "bar_close"};
   for(int i = 0; i < ArraySize(fixed); ++i) Add(row, fixed[i]);
   for(int b = 0; b < 36; ++b) Add(row, "v200_b" + IntegerToString(b));
   for(int b = 0; b < 54; ++b) Add(row, "v210_b" + IntegerToString(b));
   Add(row, "bars_calculated_v200");
   Add(row, "bars_calculated_v210");
   WriteLine(row);
}

void WriteSnapshot(const string event_kind,
                   const datetime tick_time,
                   const datetime bar_open,
                   const int shift)
{
   string row = "";
   Add(row, IntegerToString(InpCaptureMode));
   Add(row, event_kind);
   Add(row, _Symbol);
   Add(row, EnumToString(_Period));
   Add(row, TimeCell(tick_time));
   Add(row, TimeCell(bar_open));
   Add(row, IntegerToString(shift));
   Add(row, Cell(iHigh(_Symbol, _Period, shift)));
   Add(row, Cell(iLow(_Symbol, _Period, shift)));
   Add(row, Cell(iClose(_Symbol, _Period, shift)));
   double value;
   for(int b = 0; b < 36; ++b)
   {
      ReadOne(g_v200, b, shift, value);
      Add(row, Cell(value));
   }
   for(int b = 0; b < 54; ++b)
   {
      ReadOne(g_v210, b, shift, value);
      Add(row, Cell(value));
   }
   Add(row, IntegerToString(BarsCalculated(g_v200)));
   Add(row, IntegerToString(BarsCalculated(g_v210)));
   WriteLine(row);
}

void DumpHistorical()
{
   int count = Bars(_Symbol, _Period);
   if(count <= 0) return;
   if(count > InpMaxHistoricalBars) count = InpMaxHistoricalBars;
   if(BarsCalculated(g_v200) < count || BarsCalculated(g_v210) < count) return;

   datetime times[];
   double highs[], lows[], closes[];
   ArrayResize(times, count);
   ArrayResize(highs, count);
   ArrayResize(lows, count);
   ArrayResize(closes, count);
   if(CopyTime(_Symbol, _Period, 0, count, times) != count ||
      CopyHigh(_Symbol, _Period, 0, count, highs) != count ||
      CopyLow(_Symbol, _Period, 0, count, lows) != count ||
      CopyClose(_Symbol, _Period, 0, count, closes) != count)
      return;

   double v200[], v210[];
   ArrayResize(v200, 36 * count);
   ArrayResize(v210, 54 * count);
   for(int b = 0; b < 36; ++b)
   {
      double values[];
      if(!ReadAll(g_v200, b, count, values)) return;
      for(int i = 0; i < count; ++i) v200[b * count + i] = values[i];
   }
   for(int b = 0; b < 54; ++b)
   {
      double values[];
      if(!ReadAll(g_v210, b, count, values)) return;
      for(int i = 0; i < count; ++i) v210[b * count + i] = values[i];
   }

   for(int i = 0; i < count; ++i)
   {
      string row = "";
      const int shift = count - 1 - i;
      Add(row, IntegerToString(InpCaptureMode));
      Add(row, "HISTORICAL_RELOAD");
      Add(row, _Symbol);
      Add(row, EnumToString(_Period));
      Add(row, TimeCell(TimeCurrent()));
      Add(row, TimeCell(times[i]));
      Add(row, IntegerToString(shift));
      Add(row, Cell(highs[i]));
      Add(row, Cell(lows[i]));
      Add(row, Cell(closes[i]));
      for(int b = 0; b < 36; ++b) Add(row, Cell(v200[b * count + i]));
      for(int b = 0; b < 54; ++b) Add(row, Cell(v210[b * count + i]));
      Add(row, IntegerToString(BarsCalculated(g_v200)));
      Add(row, IntegerToString(BarsCalculated(g_v210)));
      WriteLine(row);
   }
   FileFlush(g_file);
   FileClose(g_file);
   g_file = INVALID_HANDLE;
   g_dumped = true;
}

int OnInit()
{
   SetIndexBuffer(0, g_probe_buffer, INDICATOR_DATA);
   ArraySetAsSeries(g_probe_buffer, true);
   g_v200 = iCustom(_Symbol, _Period, InpV200Name,
                    "Legacy Breakout Clock",
                    InpHourBegin, InpMinBegin, InpHourEnd, InpMinEnd, InpHourEndArea, InpMinEndArea,
                    "Causal State / Coverage",
                    20, true, true, true,
                    "Legacy Renderer",
                    true, clrRed, clrFuchsia, 2, 1, STYLE_SOLID, STYLE_DOT,
                    "Identity", "INST01_V200");
   g_v210 = iCustom(_Symbol, _Period, InpV210Name,
                    "Legacy Breakout Clock",
                    InpHourBegin, InpMinBegin, InpHourEnd, InpMinEnd, InpHourEndArea, InpMinEndArea,
                    "Causal State / Coverage",
                    20, true, true, true,
                    "Legacy Renderer",
                    true, clrRed, clrFuchsia, 2, 1, STYLE_SOLID, STYLE_DOT,
                    "Causal Extreme Sentinels",
                    true, false, clrViolet, clrTeal, STYLE_SOLID, 2,
                    "Identity", "INST01_V210");
   if(g_v200 == INVALID_HANDLE || g_v210 == INVALID_HANDLE)
      return INIT_FAILED;
   g_file = FileOpen(InpOutputFile, FILE_COMMON | FILE_WRITE | FILE_ANSI | FILE_SHARE_READ);
   if(g_file == INVALID_HANDLE)
      return INIT_FAILED;
   WriteHeader();
   return INIT_SUCCEEDED;
}

int OnCalculate(const int rates_total,
                const int prev_calculated,
                const datetime &time[],
                const double &open[],
                const double &high[],
                const double &low[],
                const double &close[],
                const long &tick_volume[],
                const long &volume[],
                const int &spread[])
{
   if(rates_total > 0)
      g_probe_buffer[0] = 0.0;
   if(g_file == INVALID_HANDLE) return rates_total;
   if(InpCaptureMode == 1)
   {
      if(!g_dumped) DumpHistorical();
      return rates_total;
   }
   const datetime bar = iTime(_Symbol, _Period, 0);
   if(bar <= 0) return rates_total;
   const datetime now = TimeCurrent();
   if(g_last_bar == 0)
   {
      g_last_bar = bar;
      WriteSnapshot("CURRENT_OPEN", now, bar, 0);
      ReadOne(g_v210, 36, 0, g_last_live_upper);
      ReadOne(g_v210, 37, 0, g_last_live_lower);
   }
   else if(bar != g_last_bar)
   {
      WriteSnapshot("COMPLETED_BAR", now, iTime(_Symbol, _Period, 1), 1);
      g_last_bar = bar;
      WriteSnapshot("CURRENT_OPEN", now, bar, 0);
      ReadOne(g_v210, 36, 0, g_last_live_upper);
      ReadOne(g_v210, 37, 0, g_last_live_lower);
   }
   else if(InpCaptureSentinelChanges)
   {
      double upper, lower;
      ReadOne(g_v210, 36, 0, upper);
      ReadOne(g_v210, 37, 0, lower);
      if(upper != g_last_live_upper || lower != g_last_live_lower)
      {
         g_last_live_upper = upper;
         g_last_live_lower = lower;
         WriteSnapshot("CURRENT_TICK_SENTINEL_CHANGE", now, bar, 0);
      }
   }
   FileFlush(g_file);
   return rates_total;
}

void OnDeinit(const int reason)
{
   if(g_file != INVALID_HANDLE) FileClose(g_file);
   if(g_v200 != INVALID_HANDLE) IndicatorRelease(g_v200);
   if(g_v210 != INVALID_HANDLE) IndicatorRelease(g_v210);
}
