//+------------------------------------------------------------------+
//| OBS-OPEN-SRC-01 bounded legacy-buffer oracle capture              |
//| Captures original BreakOut, translated BreakOut2, and V2 legacy  |
//| buffers without changing any indicator source.                   |
//+------------------------------------------------------------------+
#property strict

input group "Capture"
input string InpOriginalName = "BreakOut";
input string InpTranslatedName = "BreakOut2";
input string InpV2Name = "OpeningRangeGrammar_v2_00_LegacyStateMachine";
input string InpOutputFile = "OBS_OPEN_SRC01_capture.tsv";
input ENUM_TIMEFRAMES InpCaptureTimeframe = PERIOD_CURRENT;
input int InpCaptureMode = 0; // 0 online bar snapshots, 1 historical reload
input int InpMaxHistoricalBars = 20000;
input bool InpCaptureEveryTick = false;

input group "Legacy Breakout Clock"
input uint InpHourBegin = 9;
input uint InpMinBegin = 30;
input uint InpHourEnd = 9;
input uint InpMinEnd = 35;
input uint InpHourEndArea = 9;
input uint InpMinEndArea = 40;

int g_original = INVALID_HANDLE;
int g_translated = INVALID_HANDLE;
int g_v2 = INVALID_HANDLE;
int g_file = INVALID_HANDLE;
datetime g_last_bar = 0;
bool g_dumped = false;

string Cell(const double value)
{
   if(value == EMPTY_VALUE || !MathIsValidNumber(value))
      return "NA";
   return DoubleToString(value, _Digits);
}

string TimeCell(const datetime value)
{
   if(value <= 0)
      return "NA";
   return IntegerToString((long)value);
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
   if(handle == INVALID_HANDLE || CopyBuffer(handle, buffer, 0, count, values) != count)
      return false;
   return true;
}

void WriteHeader()
{
   FileWrite(g_file,
             "capture_mode", "event_kind", "symbol", "timeframe", "tick_time", "bar_open", "shift",
             "original_b0", "original_b1", "original_b2", "original_b3",
             "translated_b0", "translated_b1", "translated_b2", "translated_b3",
             "v2_legacy_b0", "v2_legacy_b1", "v2_legacy_b2", "v2_legacy_b3",
             "v2_lifecycle", "v2_geometry_known", "v2_interaction_eligible", "v2_location", "v2_grammar_event",
             "bars_calculated_original", "bars_calculated_translated", "bars_calculated_v2");
}

void WriteSnapshot(const string event_kind,
                   const datetime tick_time,
                   const datetime bar_open,
                   const int shift)
{
   double original[4], translated[4], legacy[4], value;
   for(int b = 0; b < 4; ++b)
   {
      ReadOne(g_original, b, shift, value); original[b] = value;
      ReadOne(g_translated, b, shift, value); translated[b] = value;
      ReadOne(g_v2, 17 + b, shift, value); legacy[b] = value;
   }
   double lifecycle, known, eligible, location, event;
   ReadOne(g_v2, 4, shift, lifecycle);
   ReadOne(g_v2, 25, shift, known);
   ReadOne(g_v2, 8, shift, eligible);
   ReadOne(g_v2, 9, shift, location);
   ReadOne(g_v2, 10, shift, event);

   FileWrite(g_file,
             IntegerToString(InpCaptureMode), event_kind, _Symbol, EnumToString(_Period),
             TimeCell(tick_time), TimeCell(bar_open), IntegerToString(shift),
             Cell(original[0]), Cell(original[1]), Cell(original[2]), Cell(original[3]),
             Cell(translated[0]), Cell(translated[1]), Cell(translated[2]), Cell(translated[3]),
             Cell(legacy[0]), Cell(legacy[1]), Cell(legacy[2]), Cell(legacy[3]),
             Cell(lifecycle), Cell(known), Cell(eligible), Cell(location), Cell(event),
             IntegerToString(BarsCalculated(g_original)),
             IntegerToString(BarsCalculated(g_translated)),
             IntegerToString(BarsCalculated(g_v2)));
}

void DumpHistorical()
{
   int count = Bars(_Symbol, _Period);
   if(count <= 0)
      return;
   if(count > InpMaxHistoricalBars)
      count = InpMaxHistoricalBars;
   if(BarsCalculated(g_original) < count || BarsCalculated(g_translated) < count || BarsCalculated(g_v2) < count)
      return;

   datetime times[];
   double original[], translated[], legacy[];
   ArrayResize(times, count);
   ArrayResize(original, 4 * count);
   ArrayResize(translated, 4 * count);
   ArrayResize(legacy, 4 * count);
   if(CopyTime(_Symbol, _Period, 0, count, times) != count)
      return;
   for(int b = 0; b < 4; ++b)
   {
      double values[];
      if(!ReadAll(g_original, b, count, values)) return;
      for(int index = 0; index < count; ++index) original[b * count + index] = values[index];
      if(!ReadAll(g_translated, b, count, values)) return;
      for(int index = 0; index < count; ++index) translated[b * count + index] = values[index];
      if(!ReadAll(g_v2, 17 + b, count, values)) return;
      for(int index = 0; index < count; ++index) legacy[b * count + index] = values[index];
   }
   for(int index = 0; index < count; ++index)
   {
      const int shift = count - 1 - index;
      double lifecycle, known, eligible, location, event;
      ReadOne(g_v2, 4, shift, lifecycle);
      ReadOne(g_v2, 25, shift, known);
      ReadOne(g_v2, 8, shift, eligible);
      ReadOne(g_v2, 9, shift, location);
      ReadOne(g_v2, 10, shift, event);
      FileWrite(g_file,
                IntegerToString(InpCaptureMode), "HISTORICAL_RELOAD", _Symbol, EnumToString(_Period),
                TimeCell(TimeCurrent()), TimeCell(times[index]), IntegerToString(shift),
                Cell(original[0 * count + index]), Cell(original[1 * count + index]), Cell(original[2 * count + index]), Cell(original[3 * count + index]),
                Cell(translated[0 * count + index]), Cell(translated[1 * count + index]), Cell(translated[2 * count + index]), Cell(translated[3 * count + index]),
                Cell(legacy[0 * count + index]), Cell(legacy[1 * count + index]), Cell(legacy[2 * count + index]), Cell(legacy[3 * count + index]),
                Cell(lifecycle), Cell(known), Cell(eligible), Cell(location), Cell(event),
                IntegerToString(BarsCalculated(g_original)),
                IntegerToString(BarsCalculated(g_translated)),
                IntegerToString(BarsCalculated(g_v2)));
   }
   FileFlush(g_file);
   g_dumped = true;
}

int OnInit()
{
   g_original = iCustom(_Symbol, _Period, InpOriginalName,
                        InpHourBegin, InpMinBegin, InpHourEnd, InpMinEnd, InpHourEndArea, InpMinEndArea);
   g_translated = iCustom(_Symbol, _Period, InpTranslatedName,
                          InpHourBegin, InpMinBegin, InpHourEnd, InpMinEnd, InpHourEndArea, InpMinEndArea);
   // MT5 includes every `input group` heading in the runtime iCustom ABI.
   // Supply the complete grouped parameter stream so the six legacy clock
   // values bind to the same fields as the original BreakOut oracle.
   g_v2 = iCustom(_Symbol, _Period, InpV2Name,
                  "Legacy Breakout Clock",
                  InpHourBegin, InpMinBegin, InpHourEnd, InpMinEnd, InpHourEndArea, InpMinEndArea,
                  "Causal State / Coverage",
                  20, true, true, true,
                  "Legacy Renderer",
                  true, clrRed, clrFuchsia, 2, 1, STYLE_SOLID, STYLE_DOT,
                  "Identity", "SRC01");
   if(g_original == INVALID_HANDLE || g_translated == INVALID_HANDLE || g_v2 == INVALID_HANDLE)
      return INIT_FAILED;
   g_file = FileOpen(InpOutputFile, FILE_COMMON | FILE_WRITE | FILE_CSV | FILE_ANSI, '\t');
   if(g_file == INVALID_HANDLE)
      return INIT_FAILED;
   WriteHeader();
   return INIT_SUCCEEDED;
}

void OnTick()
{
   if(g_file == INVALID_HANDLE)
      return;
   if(InpCaptureMode == 1)
   {
      if(!g_dumped)
         DumpHistorical();
      return;
   }

   const datetime bar = iTime(_Symbol, _Period, 0);
   if(bar <= 0)
      return;
   const datetime tick_time = TimeCurrent();
   if(g_last_bar == 0)
   {
      g_last_bar = bar;
      WriteSnapshot("CURRENT_OPEN", tick_time, bar, 0);
   }
   else if(bar != g_last_bar)
   {
      WriteSnapshot("COMPLETED_BAR", tick_time, iTime(_Symbol, _Period, 1), 1);
      g_last_bar = bar;
      WriteSnapshot("CURRENT_OPEN", tick_time, bar, 0);
   }
   else if(InpCaptureEveryTick)
      WriteSnapshot("CURRENT_TICK", tick_time, bar, 0);
   FileFlush(g_file);
}

void OnDeinit(const int reason)
{
   if(g_file != INVALID_HANDLE)
      FileClose(g_file);
   if(g_original != INVALID_HANDLE) IndicatorRelease(g_original);
   if(g_translated != INVALID_HANDLE) IndicatorRelease(g_translated);
   if(g_v2 != INVALID_HANDLE) IndicatorRelease(g_v2);
}
