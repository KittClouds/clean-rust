//+------------------------------------------------------------------+
//|     OpeningRangeGrammar_v2_10_ExtremeSentinels.mq5              |
//| Legacy geometry + causal state + grammar + running extremes       |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026, Indices Group (Pty) Ltd"
#property version   "2.10"
#property description "Legacy Breakout geometry is preserved in four compatibility buffers."
#property description "Causal range state is explicit: developing -> freeze pending -> frozen -> complete."
#property description "Completed chart candles own the post-freeze interaction grammar."
#property description "Causal extreme sentinels track running session highs/lows without claiming terminal extrema."

#property indicator_chart_window
#property indicator_buffers 54
#property indicator_plots   54

// -------------------------------------------------------------------
// LEGACY CLOCK CONTRACT
//
// These six inputs intentionally mirror Breakout.mq5. The legacy layer
// preserves its PERIOD_CURRENT semantics, inclusive configured end bar,
// and overlapping period/area display on the configured end boundary.
// -------------------------------------------------------------------
input group "Legacy Breakout Clock"
input uint InpHourBegin   = 0;   // "Period" Hour begin
input uint InpMinBegin    = 0;   // "Period" Minutes begin
input uint InpHourEnd     = 5;   // "Period" Hour end
input uint InpMinEnd      = 0;   // "Period" Minutes end
input uint InpHourEndArea = 23;  // "Area" Hour end
input uint InpMinEndArea  = 0;   // "Area" Minutes end

input group "Causal State / Coverage"
input int  InpHistoryDays               = 20;
input bool InpRequireExactStartAlignment = true;
input bool InpRequireRangeContinuity     = true;
input bool InpRequireChartContinuity     = true;

input group "Legacy Renderer"
input bool            InpShowLegacyLines = true;
input color           InpPeriodColor     = clrRed;
input color           InpAreaColor       = clrFuchsia;
input int             InpPeriodWidth     = 2;
input int             InpAreaWidth       = 1;
input ENUM_LINE_STYLE InpPeriodStyle     = STYLE_SOLID;
input ENUM_LINE_STYLE InpAreaStyle       = STYLE_DOT;

input group "Causal Extreme Sentinels"
input bool            InpEnableExtremeSentinels = true;
input bool            InpShowExtremeSentinels   = true;
input color           InpUpperSentinelColor     = clrViolet;
input color           InpLowerSentinelColor     = clrTeal;
input ENUM_LINE_STYLE InpExtremeSentinelStyle   = STYLE_SOLID;
input int             InpExtremeSentinelWidth   = 2;

input group "Identity"
input string InpUniqueId = "01";

// -------------------------------------------------------------------
// BUFFER CONTRACT
//
// Core grammar compatibility (same logical order as v1.02 FullState):
//  0 RangeHigh                final causal geometry only
//  1 RangeLow
//  2 RangeMid
//  3 RangeWidth
//  4 LifecycleState           -1 NOT_EVALUABLE, 0 WAITING,
//                              1 COLLECTING, 2 FROZEN, 3 COMPLETE
//  5 RangeOpenFlag
//  6 RangeClosedFlag
//  7 AreaActiveFlag           causal post-freeze area
//  8 InteractionEligible
//  9 LocationState
// 10 GrammarEvent
// 11 OutsideRunBars
// 12 FirstOutsideSide         +1 above, -1 below, 0 none observed
// 13 AboveExcursionCount
// 14 BelowExcursionCount
// 15 FailedAboveCount
// 16 FailedBelowCount
//
// Exact legacy Breakout compatibility buffers:
// 17 LegacyUpperPeriod
// 18 LegacyLowerPeriod
// 19 LegacyUpperArea
// 20 LegacyLowerArea
//
// Additional explicit machine state / timing:
// 21 DevelopingHigh           geometry known through this bar only
// 22 DevelopingLow
// 23 FreezePendingFlag        end bar is still part of range
// 24 LegacyDisplayPhase       0 NONE, 1 PERIOD, 2 AREA, 3 PERIOD_AND_AREA
// 25 GeometryKnownFlag        final geometry causally committed
// 26 SourceCoverageFlag       1 qualified, 0 unresolved/failed
// 27 ConfigRangeStartTime
// 28 ActualRangeStartBarOpen
// 29 ConfigRangeEndTime
// 30 ActualRangeEndBarOpen
// 31 FreezeCommitTime         actual end-bar open + chart period
// 32 ConfigAreaEndTime
// 33 ActualAreaEndBarOpen
// 34 AreaCloseCommitTime      actual area-end bar open + chart period
// 35 SessionId                configured range-start civil day, epoch seconds
//
// Causal running-extreme sentinels (append-only; v2.00 indices remain stable):
// 36 UpperExtremeSentinel      plotted; completed bars are committed, bar 0 may be provisional
// 37 LowerExtremeSentinel
// 38 UpperExtremeCommitted     last completed-bar running high
// 39 LowerExtremeCommitted     last completed-bar running low
// 40 UpperExtremeBirthTime     deterministic knowledge time = source bar close
// 41 LowerExtremeBirthTime
// 42 NewUpperExtremeFlag       completed-bar event only
// 43 NewLowerExtremeFlag
// 44 UpperExtremeAgeBars       completed bars since current candidate was established
// 45 LowerExtremeAgeBars
// 46 UpperGivebackClose        upper sentinel - close
// 47 LowerGivebackClose        close - lower sentinel
// 48 UpperExtensionFromRange   upper sentinel - frozen range high, after freeze only
// 49 LowerExtensionFromRange   frozen range low - lower sentinel, after freeze only
// 50 UpperExtremeCandidateId   monotone within session; first candidate = 1
// 51 LowerExtremeCandidateId
// 52 SentinelWindowActive      range-start through area-end observation window
// 53 SentinelCoverageFlag      1 only while the sentinel path remains causally qualified
//
// Sentinels never claim "session high" or "session low" before the observation
// window ends. They mean only highest/lowest causally observed value so far.
// The distinction between 17..20 and 0..16 is deliberate:
// legacy display history may repaint/backfill; causal state never claims final
// geometry before FreezeCommitTime.
// -------------------------------------------------------------------
double RangeHighBuffer[];
double RangeLowBuffer[];
double RangeMidBuffer[];
double RangeWidthBuffer[];
double LifecycleBuffer[];
double RangeOpenBuffer[];
double RangeClosedBuffer[];
double AreaActiveBuffer[];
double InteractionEligibleBuffer[];
double LocationBuffer[];
double GrammarEventBuffer[];
double OutsideRunBuffer[];
double FirstOutsideSideBuffer[];
double AboveExcursionCountBuffer[];
double BelowExcursionCountBuffer[];
double FailedAboveCountBuffer[];
double FailedBelowCountBuffer[];

double LegacyUpperPeriodBuffer[];
double LegacyLowerPeriodBuffer[];
double LegacyUpperAreaBuffer[];
double LegacyLowerAreaBuffer[];

double DevelopingHighBuffer[];
double DevelopingLowBuffer[];
double FreezePendingBuffer[];
double LegacyDisplayPhaseBuffer[];
double GeometryKnownBuffer[];
double SourceCoverageBuffer[];
double ConfigRangeStartBuffer[];
double ActualRangeStartBuffer[];
double ConfigRangeEndBuffer[];
double ActualRangeEndBuffer[];
double FreezeCommitBuffer[];
double ConfigAreaEndBuffer[];
double ActualAreaEndBuffer[];
double AreaCloseCommitBuffer[];
double SessionIdBuffer[];

double UpperExtremeSentinelBuffer[];
double LowerExtremeSentinelBuffer[];
double UpperExtremeCommittedBuffer[];
double LowerExtremeCommittedBuffer[];
double UpperExtremeBirthBuffer[];
double LowerExtremeBirthBuffer[];
double NewUpperExtremeBuffer[];
double NewLowerExtremeBuffer[];
double UpperExtremeAgeBuffer[];
double LowerExtremeAgeBuffer[];
double UpperGivebackBuffer[];
double LowerGivebackBuffer[];
double UpperExtensionRangeBuffer[];
double LowerExtensionRangeBuffer[];
double UpperCandidateIdBuffer[];
double LowerCandidateIdBuffer[];
double SentinelWindowActiveBuffer[];
double SentinelCoverageBuffer[];

enum ENUM_ORSM_STATE
{
   ORSM_NOT_EVALUABLE = -1,
   ORSM_WAITING       = 0,
   ORSM_COLLECTING    = 1,
   ORSM_FROZEN        = 2,
   ORSM_COMPLETE      = 3
};

enum ENUM_ORSM_DISPLAY_PHASE
{
   ORSM_DISPLAY_NONE            = 0,
   ORSM_DISPLAY_PERIOD          = 1,
   ORSM_DISPLAY_AREA            = 2,
   ORSM_DISPLAY_PERIOD_AND_AREA = 3
};

enum ENUM_ORSM_LOCATION
{
   ORSM_LOC_NOT_AVAILABLE = 0,
   ORSM_LOC_IN_ZONE       = 1,
   ORSM_LOC_ABOVE         = 2,
   ORSM_LOC_BELOW         = 3
};

enum ENUM_ORSM_EVENT
{
   ORSM_EVENT_NONE                 = 0,
   ORSM_EVENT_IN_ZONE              = 1,
   ORSM_EVENT_FIRST_CLOSE_ABOVE    = 2,
   ORSM_EVENT_PERSIST_ABOVE        = 3,
   ORSM_EVENT_FAILED_ABOVE         = 4,
   ORSM_EVENT_RETURN_FROM_ABOVE    = 5,
   ORSM_EVENT_FIRST_CLOSE_BELOW    = 6,
   ORSM_EVENT_PERSIST_BELOW        = 7,
   ORSM_EVENT_FAILED_BELOW         = 8,
   ORSM_EVENT_RETURN_FROM_BELOW    = 9,
   ORSM_EVENT_CROSS_ABOVE_TO_BELOW = 10,
   ORSM_EVENT_CROSS_BELOW_TO_ABOVE = 11,
   ORSM_EVENT_RESUME_IN_ZONE       = 12,
   ORSM_EVENT_RESUME_ABOVE         = 13,
   ORSM_EVENT_RESUME_BELOW         = 14
};

struct ORSM_SESSION
{
   datetime day_start;
   datetime configured_start;
   datetime configured_end;
   datetime configured_area_end;

   datetime actual_start_open;
   datetime actual_end_open;
   datetime freeze_commit;
   datetime actual_area_end_open;
   datetime area_close_commit;

   int begin_shift;
   int end_shift;
   int area_shift;

   double frozen_high;
   double frozen_low;
   bool   frozen_geometry_ready;

   bool start_resolved;
   bool end_resolved;
   bool area_resolved;
   bool start_aligned;
   bool range_continuous;
   bool evaluable;

   double running_high;
   double running_low;
   bool   running_has_geometry;

   // Causal running-extreme sentinels. These are independent from the frozen
   // range geometry and from the legacy renderer. They update only on completed
   // bars; bar 0 receives a non-persistent provisional display value.
   double   upper_extreme;
   double   lower_extreme;
   bool     extreme_has_geometry;
   datetime upper_extreme_birth;
   datetime lower_extreme_birth;
   int      upper_extreme_age_bars;
   int      lower_extreme_age_bars;
   long     upper_extreme_candidate_id;
   long     lower_extreme_candidate_id;
   datetime sentinel_last_committed_bar_open;
   bool     sentinel_gap_seen;
};

struct ORSM_TRACK
{
   datetime session_id;
   int      previous_location;
   int      outside_run_bars;
   datetime last_eligible_bar_open;

   int first_outside_side;
   int above_excursions;
   int below_excursions;
   int failed_above;
   int failed_below;
};

ORSM_SESSION g_sessions[];
ORSM_TRACK   g_tracks[];

datetime g_last_machine_bar0 = 0;
int      g_period_seconds     = 0;

// Original Breakout-compatible clamped clock internals.
int  g_hour_begin  = 0;
int  g_min_begin   = 0;
int  g_hour_end    = 0;
int  g_min_end     = 0;
int  g_hour_box_end = 0;
int  g_min_box_end  = 0;
long g_period_begin_min = 0;
long g_period_end_min   = 0;
long g_box_end_min      = 0;

//+------------------------------------------------------------------+
string SanitizeId(string value)
{
   StringReplace(value, " ", "_");
   StringReplace(value, ".", "_");
   StringReplace(value, "-", "_");
   return value;
}

//+------------------------------------------------------------------+
datetime DayStart(const datetime t)
{
   MqlDateTime s;
   TimeToStruct(t, s);
   s.hour = 0;
   s.min  = 0;
   s.sec  = 0;
   return StructToTime(s);
}

//+------------------------------------------------------------------+
datetime PreviousDayStart(const datetime day_start)
{
   // Midday subtraction avoids edge ambiguity around civil-day boundaries.
   return DayStart(day_start - 12 * 3600);
}

//+------------------------------------------------------------------+
datetime AtMinuteOfDay(const datetime day_start, const int minute_of_day)
{
   return day_start + (datetime)(minute_of_day * 60);
}

//+------------------------------------------------------------------+
int MinuteOfDay(const datetime t)
{
   MqlDateTime tm;
   TimeToStruct(t, tm);
   return tm.hour * 60 + tm.min;
}

//+------------------------------------------------------------------+
bool LegacyPeriodMinute(const int cur_min)
{
   return ((g_period_end_min > g_period_begin_min &&
            cur_min >= g_period_begin_min && cur_min <= g_period_end_min) ||
           (g_period_end_min < g_period_begin_min &&
            (cur_min >= g_period_begin_min || cur_min <= g_period_end_min)));
}

//+------------------------------------------------------------------+
bool LegacyAreaMinute(const int cur_min)
{
   return ((g_box_end_min > g_period_end_min &&
            cur_min >= g_period_end_min && cur_min <= g_box_end_min) ||
           (g_box_end_min < g_period_end_min &&
            (cur_min >= g_period_end_min || cur_min <= g_box_end_min)));
}

//+------------------------------------------------------------------+
int LegacyDisplayPhaseAt(const datetime bar_open)
{
   const int cur_min = MinuteOfDay(bar_open);
   const bool period = LegacyPeriodMinute(cur_min);
   const bool area   = LegacyAreaMinute(cur_min);

   if(period && area)
      return ORSM_DISPLAY_PERIOD_AND_AREA;
   if(period)
      return ORSM_DISPLAY_PERIOD;
   if(area)
      return ORSM_DISPLAY_AREA;
   return ORSM_DISPLAY_NONE;
}

// -------------------------------------------------------------------
// Exact helper logic copied from the recovered Breakout source.
// -------------------------------------------------------------------
int LegacyBarShift(const string symbol_name,
                   const ENUM_TIMEFRAMES timeframe,
                   const datetime target,
                   const bool exact = false)
{
   datetime last_bar;
   if(!SeriesInfoInteger(symbol_name, timeframe, SERIES_LASTBAR_DATE, last_bar))
   {
      datetime array[1];
      if(CopyTime(symbol_name, timeframe, 0, 1, array) == 1)
         last_bar = array[0];
      else
         return WRONG_VALUE;
   }

   if(target > last_bar)
      return 0;

   const int shift = Bars(symbol_name, timeframe, target, last_bar);
   datetime array[1];
   if(CopyTime(symbol_name, timeframe, target, 1, array) == 1)
      return (array[0] == target
              ? shift - 1
              : exact && target > array[0] + PeriodSeconds(timeframe)
                ? WRONG_VALUE
                : shift);

   return WRONG_VALUE;
}

//+------------------------------------------------------------------+
int LegacyFindBar(const int hour, const int minutes, const datetime t_ref)
{
   MqlDateTime tm;
   TimeToStruct(t_ref, tm);
   tm.hour = hour;
   tm.min  = minutes;
   tm.sec  = 0;

   datetime target = StructToTime(tm);
   if(target > t_ref)
      target -= 86400;

   return LegacyBarShift(_Symbol, PERIOD_CURRENT, target, false);
}

//+------------------------------------------------------------------+
int LegacyHighest(const int count, const int start)
{
   if(count <= 0 || start < 0)
      return WRONG_VALUE;

   double array[];
   ArraySetAsSeries(array, true);
   if(CopyHigh(_Symbol, PERIOD_CURRENT, start, count, array) == count)
      return ArrayMaximum(array) + start;

   return WRONG_VALUE;
}

//+------------------------------------------------------------------+
int LegacyLowest(const int count, const int start)
{
   if(count <= 0 || start < 0)
      return WRONG_VALUE;

   double array[];
   ArraySetAsSeries(array, true);
   if(CopyLow(_Symbol, PERIOD_CURRENT, start, count, array) == count)
      return ArrayMinimum(array) + start;

   return WRONG_VALUE;
}

//+------------------------------------------------------------------+
void ConfigureHiddenPlot(const int index, const string label)
{
   PlotIndexSetInteger(index, PLOT_DRAW_TYPE, DRAW_NONE);
   PlotIndexSetInteger(index, PLOT_SHOW_DATA, true);
   PlotIndexSetString(index, PLOT_LABEL, label);
}

//+------------------------------------------------------------------+
void ConfigureLegacyLine(const int index,
                         const string label,
                         const color c,
                         const ENUM_LINE_STYLE style,
                         const int width)
{
   PlotIndexSetInteger(index,
                       PLOT_DRAW_TYPE,
                       InpShowLegacyLines ? DRAW_LINE : DRAW_NONE);
   PlotIndexSetInteger(index, PLOT_SHOW_DATA, true);
   PlotIndexSetInteger(index, PLOT_LINE_COLOR, c);
   PlotIndexSetInteger(index, PLOT_LINE_STYLE, style);
   PlotIndexSetInteger(index, PLOT_LINE_WIDTH, width);
   PlotIndexSetString(index, PLOT_LABEL, label);
}

//+------------------------------------------------------------------+
void ConfigureExtremeLine(const int index,
                          const string label,
                          const color c)
{
   PlotIndexSetInteger(index,
                       PLOT_DRAW_TYPE,
                       (InpEnableExtremeSentinels && InpShowExtremeSentinels)
                       ? DRAW_LINE : DRAW_NONE);
   PlotIndexSetInteger(index, PLOT_SHOW_DATA, true);
   PlotIndexSetInteger(index, PLOT_LINE_COLOR, c);
   PlotIndexSetInteger(index, PLOT_LINE_STYLE, InpExtremeSentinelStyle);
   PlotIndexSetInteger(index, PLOT_LINE_WIDTH, InpExtremeSentinelWidth);
   PlotIndexSetString(index, PLOT_LABEL, label);
}

//+------------------------------------------------------------------+
bool ValidateInputs()
{
   if(InpHistoryDays < 1 || InpHistoryDays > 3650)
      return false;

   if(InpPeriodWidth < 1 || InpPeriodWidth > 5 ||
      InpAreaWidth < 1 || InpAreaWidth > 5 ||
      InpExtremeSentinelWidth < 1 || InpExtremeSentinelWidth > 5)
      return false;

   g_period_seconds = PeriodSeconds(_Period);
   if(g_period_seconds <= 0)
      return false;

   // Preserve Breakout's clamp semantics.
   g_hour_begin = (int)(InpHourBegin > 23 ? 23 : InpHourBegin);
   g_min_begin  = (int)(InpMinBegin > 59 ? 59 : InpMinBegin);
   g_hour_end   = (int)(InpHourEnd > 23 ? 23 : InpHourEnd);
   g_min_end    = (int)(InpMinEnd > 59 ? 59 : InpMinEnd);
   g_hour_box_end = (int)(InpHourEndArea > 23
                           ? 23
                           : InpHourEndArea < (uint)g_hour_end
                             ? g_hour_end
                             : InpHourEndArea);
   g_min_box_end = (int)(InpMinEndArea > 59 ? 59 : InpMinEndArea);

   g_period_begin_min = 60 * g_hour_begin + g_min_begin;
   g_period_end_min   = 60 * g_hour_end   + g_min_end;
   g_box_end_min      = 60 * g_hour_box_end + g_min_box_end;

   return true;
}

//+------------------------------------------------------------------+
int OnInit()
{
   if(!ValidateInputs())
   {
      Print("OpeningRangeGrammar v2: invalid inputs.");
      return INIT_PARAMETERS_INCORRECT;
   }

   SetIndexBuffer(0,  RangeHighBuffer,               INDICATOR_DATA);
   SetIndexBuffer(1,  RangeLowBuffer,                INDICATOR_DATA);
   SetIndexBuffer(2,  RangeMidBuffer,                INDICATOR_DATA);
   SetIndexBuffer(3,  RangeWidthBuffer,              INDICATOR_DATA);
   SetIndexBuffer(4,  LifecycleBuffer,               INDICATOR_DATA);
   SetIndexBuffer(5,  RangeOpenBuffer,               INDICATOR_DATA);
   SetIndexBuffer(6,  RangeClosedBuffer,             INDICATOR_DATA);
   SetIndexBuffer(7,  AreaActiveBuffer,              INDICATOR_DATA);
   SetIndexBuffer(8,  InteractionEligibleBuffer,     INDICATOR_DATA);
   SetIndexBuffer(9,  LocationBuffer,                INDICATOR_DATA);
   SetIndexBuffer(10, GrammarEventBuffer,            INDICATOR_DATA);
   SetIndexBuffer(11, OutsideRunBuffer,              INDICATOR_DATA);
   SetIndexBuffer(12, FirstOutsideSideBuffer,        INDICATOR_DATA);
   SetIndexBuffer(13, AboveExcursionCountBuffer,     INDICATOR_DATA);
   SetIndexBuffer(14, BelowExcursionCountBuffer,     INDICATOR_DATA);
   SetIndexBuffer(15, FailedAboveCountBuffer,        INDICATOR_DATA);
   SetIndexBuffer(16, FailedBelowCountBuffer,        INDICATOR_DATA);

   SetIndexBuffer(17, LegacyUpperPeriodBuffer,       INDICATOR_DATA);
   SetIndexBuffer(18, LegacyLowerPeriodBuffer,       INDICATOR_DATA);
   SetIndexBuffer(19, LegacyUpperAreaBuffer,         INDICATOR_DATA);
   SetIndexBuffer(20, LegacyLowerAreaBuffer,         INDICATOR_DATA);

   SetIndexBuffer(21, DevelopingHighBuffer,          INDICATOR_DATA);
   SetIndexBuffer(22, DevelopingLowBuffer,           INDICATOR_DATA);
   SetIndexBuffer(23, FreezePendingBuffer,           INDICATOR_DATA);
   SetIndexBuffer(24, LegacyDisplayPhaseBuffer,      INDICATOR_DATA);
   SetIndexBuffer(25, GeometryKnownBuffer,           INDICATOR_DATA);
   SetIndexBuffer(26, SourceCoverageBuffer,          INDICATOR_DATA);
   SetIndexBuffer(27, ConfigRangeStartBuffer,        INDICATOR_DATA);
   SetIndexBuffer(28, ActualRangeStartBuffer,        INDICATOR_DATA);
   SetIndexBuffer(29, ConfigRangeEndBuffer,          INDICATOR_DATA);
   SetIndexBuffer(30, ActualRangeEndBuffer,          INDICATOR_DATA);
   SetIndexBuffer(31, FreezeCommitBuffer,            INDICATOR_DATA);
   SetIndexBuffer(32, ConfigAreaEndBuffer,           INDICATOR_DATA);
   SetIndexBuffer(33, ActualAreaEndBuffer,           INDICATOR_DATA);
   SetIndexBuffer(34, AreaCloseCommitBuffer,         INDICATOR_DATA);
   SetIndexBuffer(35, SessionIdBuffer,               INDICATOR_DATA);

   SetIndexBuffer(36, UpperExtremeSentinelBuffer,      INDICATOR_DATA);
   SetIndexBuffer(37, LowerExtremeSentinelBuffer,      INDICATOR_DATA);
   SetIndexBuffer(38, UpperExtremeCommittedBuffer,     INDICATOR_DATA);
   SetIndexBuffer(39, LowerExtremeCommittedBuffer,     INDICATOR_DATA);
   SetIndexBuffer(40, UpperExtremeBirthBuffer,         INDICATOR_DATA);
   SetIndexBuffer(41, LowerExtremeBirthBuffer,         INDICATOR_DATA);
   SetIndexBuffer(42, NewUpperExtremeBuffer,           INDICATOR_DATA);
   SetIndexBuffer(43, NewLowerExtremeBuffer,           INDICATOR_DATA);
   SetIndexBuffer(44, UpperExtremeAgeBuffer,           INDICATOR_DATA);
   SetIndexBuffer(45, LowerExtremeAgeBuffer,           INDICATOR_DATA);
   SetIndexBuffer(46, UpperGivebackBuffer,             INDICATOR_DATA);
   SetIndexBuffer(47, LowerGivebackBuffer,             INDICATOR_DATA);
   SetIndexBuffer(48, UpperExtensionRangeBuffer,       INDICATOR_DATA);
   SetIndexBuffer(49, LowerExtensionRangeBuffer,       INDICATOR_DATA);
   SetIndexBuffer(50, UpperCandidateIdBuffer,          INDICATOR_DATA);
   SetIndexBuffer(51, LowerCandidateIdBuffer,          INDICATOR_DATA);
   SetIndexBuffer(52, SentinelWindowActiveBuffer,      INDICATOR_DATA);
   SetIndexBuffer(53, SentinelCoverageBuffer,          INDICATOR_DATA);

   ArraySetAsSeries(RangeHighBuffer, true);
   ArraySetAsSeries(RangeLowBuffer, true);
   ArraySetAsSeries(RangeMidBuffer, true);
   ArraySetAsSeries(RangeWidthBuffer, true);
   ArraySetAsSeries(LifecycleBuffer, true);
   ArraySetAsSeries(RangeOpenBuffer, true);
   ArraySetAsSeries(RangeClosedBuffer, true);
   ArraySetAsSeries(AreaActiveBuffer, true);
   ArraySetAsSeries(InteractionEligibleBuffer, true);
   ArraySetAsSeries(LocationBuffer, true);
   ArraySetAsSeries(GrammarEventBuffer, true);
   ArraySetAsSeries(OutsideRunBuffer, true);
   ArraySetAsSeries(FirstOutsideSideBuffer, true);
   ArraySetAsSeries(AboveExcursionCountBuffer, true);
   ArraySetAsSeries(BelowExcursionCountBuffer, true);
   ArraySetAsSeries(FailedAboveCountBuffer, true);
   ArraySetAsSeries(FailedBelowCountBuffer, true);
   ArraySetAsSeries(LegacyUpperPeriodBuffer, true);
   ArraySetAsSeries(LegacyLowerPeriodBuffer, true);
   ArraySetAsSeries(LegacyUpperAreaBuffer, true);
   ArraySetAsSeries(LegacyLowerAreaBuffer, true);
   ArraySetAsSeries(DevelopingHighBuffer, true);
   ArraySetAsSeries(DevelopingLowBuffer, true);
   ArraySetAsSeries(FreezePendingBuffer, true);
   ArraySetAsSeries(LegacyDisplayPhaseBuffer, true);
   ArraySetAsSeries(GeometryKnownBuffer, true);
   ArraySetAsSeries(SourceCoverageBuffer, true);
   ArraySetAsSeries(ConfigRangeStartBuffer, true);
   ArraySetAsSeries(ActualRangeStartBuffer, true);
   ArraySetAsSeries(ConfigRangeEndBuffer, true);
   ArraySetAsSeries(ActualRangeEndBuffer, true);
   ArraySetAsSeries(FreezeCommitBuffer, true);
   ArraySetAsSeries(ConfigAreaEndBuffer, true);
   ArraySetAsSeries(ActualAreaEndBuffer, true);
   ArraySetAsSeries(AreaCloseCommitBuffer, true);
   ArraySetAsSeries(SessionIdBuffer, true);
   ArraySetAsSeries(UpperExtremeSentinelBuffer, true);
   ArraySetAsSeries(LowerExtremeSentinelBuffer, true);
   ArraySetAsSeries(UpperExtremeCommittedBuffer, true);
   ArraySetAsSeries(LowerExtremeCommittedBuffer, true);
   ArraySetAsSeries(UpperExtremeBirthBuffer, true);
   ArraySetAsSeries(LowerExtremeBirthBuffer, true);
   ArraySetAsSeries(NewUpperExtremeBuffer, true);
   ArraySetAsSeries(NewLowerExtremeBuffer, true);
   ArraySetAsSeries(UpperExtremeAgeBuffer, true);
   ArraySetAsSeries(LowerExtremeAgeBuffer, true);
   ArraySetAsSeries(UpperGivebackBuffer, true);
   ArraySetAsSeries(LowerGivebackBuffer, true);
   ArraySetAsSeries(UpperExtensionRangeBuffer, true);
   ArraySetAsSeries(LowerExtensionRangeBuffer, true);
   ArraySetAsSeries(UpperCandidateIdBuffer, true);
   ArraySetAsSeries(LowerCandidateIdBuffer, true);
   ArraySetAsSeries(SentinelWindowActiveBuffer, true);
   ArraySetAsSeries(SentinelCoverageBuffer, true);

   ConfigureHiddenPlot(0,  "Range High");
   ConfigureHiddenPlot(1,  "Range Low");
   ConfigureHiddenPlot(2,  "Range Mid");
   ConfigureHiddenPlot(3,  "Range Width");
   ConfigureHiddenPlot(4,  "Lifecycle State");
   ConfigureHiddenPlot(5,  "Range Open");
   ConfigureHiddenPlot(6,  "Range Closed");
   ConfigureHiddenPlot(7,  "Area Active");
   ConfigureHiddenPlot(8,  "Interaction Eligible");
   ConfigureHiddenPlot(9,  "Location State");
   ConfigureHiddenPlot(10, "Grammar Event");
   ConfigureHiddenPlot(11, "Outside Run Bars");
   ConfigureHiddenPlot(12, "First Outside Side");
   ConfigureHiddenPlot(13, "Above Excursion Count");
   ConfigureHiddenPlot(14, "Below Excursion Count");
   ConfigureHiddenPlot(15, "Failed Above Count");
   ConfigureHiddenPlot(16, "Failed Below Count");

   ConfigureLegacyLine(17, "Upper period", InpPeriodColor, InpPeriodStyle, InpPeriodWidth);
   ConfigureLegacyLine(18, "Lower period", InpPeriodColor, InpPeriodStyle, InpPeriodWidth);
   ConfigureLegacyLine(19, "Upper area",   InpAreaColor,   InpAreaStyle,   InpAreaWidth);
   ConfigureLegacyLine(20, "Lower area",   InpAreaColor,   InpAreaStyle,   InpAreaWidth);

   ConfigureHiddenPlot(21, "Developing High");
   ConfigureHiddenPlot(22, "Developing Low");
   ConfigureHiddenPlot(23, "Freeze Pending");
   ConfigureHiddenPlot(24, "Legacy Display Phase");
   ConfigureHiddenPlot(25, "Geometry Known");
   ConfigureHiddenPlot(26, "Source Coverage");
   ConfigureHiddenPlot(27, "Configured Range Start");
   ConfigureHiddenPlot(28, "Actual Range Start Bar Open");
   ConfigureHiddenPlot(29, "Configured Range End");
   ConfigureHiddenPlot(30, "Actual Range End Bar Open");
   ConfigureHiddenPlot(31, "Freeze Commit Time");
   ConfigureHiddenPlot(32, "Configured Area End");
   ConfigureHiddenPlot(33, "Actual Area End Bar Open");
   ConfigureHiddenPlot(34, "Area Close Commit Time");
   ConfigureHiddenPlot(35, "Session Id");

   ConfigureExtremeLine(36, "Upper Extreme Sentinel", InpUpperSentinelColor);
   ConfigureExtremeLine(37, "Lower Extreme Sentinel", InpLowerSentinelColor);
   ConfigureHiddenPlot(38, "Upper Extreme Committed");
   ConfigureHiddenPlot(39, "Lower Extreme Committed");
   ConfigureHiddenPlot(40, "Upper Extreme Birth Time");
   ConfigureHiddenPlot(41, "Lower Extreme Birth Time");
   ConfigureHiddenPlot(42, "New Upper Extreme");
   ConfigureHiddenPlot(43, "New Lower Extreme");
   ConfigureHiddenPlot(44, "Upper Extreme Age Bars");
   ConfigureHiddenPlot(45, "Lower Extreme Age Bars");
   ConfigureHiddenPlot(46, "Upper Giveback Close");
   ConfigureHiddenPlot(47, "Lower Giveback Close");
   ConfigureHiddenPlot(48, "Upper Extension From Range");
   ConfigureHiddenPlot(49, "Lower Extension From Range");
   ConfigureHiddenPlot(50, "Upper Extreme Candidate Id");
   ConfigureHiddenPlot(51, "Lower Extreme Candidate Id");
   ConfigureHiddenPlot(52, "Sentinel Window Active");
   ConfigureHiddenPlot(53, "Sentinel Coverage");

   IndicatorSetInteger(INDICATOR_DIGITS, _Digits);
   IndicatorSetString(INDICATOR_SHORTNAME,
                      "Opening Range State Grammar + Extreme Sentinels [" +
                      SanitizeId(InpUniqueId) + "]");

   ArrayResize(g_sessions, 0);
   ArrayResize(g_tracks, 0);
   g_last_machine_bar0 = 0;

   return INIT_SUCCEEDED;
}

// -------------------------------------------------------------------
// LEGACY COMPATIBILITY LAYER
// This is intentionally a direct semantic translation of Breakout.mq5.
// -------------------------------------------------------------------
void CalculateLegacyBuffers(const int rates_total,
                            const int prev_calculated,
                            const datetime &time[],
                            const double &high[],
                            const double &low[])
{
   int limit = rates_total - prev_calculated;

   if(limit > 1)
   {
      limit = rates_total - 1;
      ArrayInitialize(LegacyUpperPeriodBuffer, EMPTY_VALUE);
      ArrayInitialize(LegacyLowerPeriodBuffer, EMPTY_VALUE);
      ArrayInitialize(LegacyUpperAreaBuffer, EMPTY_VALUE);
      ArrayInitialize(LegacyLowerAreaBuffer, EMPTY_VALUE);
   }

   for(int i = limit; i >= 0 && !IsStopped(); --i)
   {
      const int cur_min = MinuteOfDay(time[i]);

      if(LegacyPeriodMinute(cur_min))
      {
         const int begin_bar = LegacyFindBar(g_hour_begin, g_min_begin, time[i]);

         if(begin_bar != WRONG_VALUE && begin_bar >= i && begin_bar < rates_total)
         {
            const int hb = LegacyHighest(begin_bar - i + 1, i);
            const int lb = LegacyLowest(begin_bar - i + 1, i);

            if(hb != WRONG_VALUE && lb != WRONG_VALUE &&
               hb >= 0 && hb < rates_total && lb >= 0 && lb < rates_total)
            {
               const double max_price = high[hb];
               const double min_price = low[lb];

               for(int j = begin_bar; j >= i; --j)
               {
                  LegacyUpperPeriodBuffer[j] = max_price;
                  LegacyLowerPeriodBuffer[j] = min_price;
               }
            }
         }
      }
      else
      {
         LegacyUpperPeriodBuffer[i] = EMPTY_VALUE;
         LegacyLowerPeriodBuffer[i] = EMPTY_VALUE;
      }

      if(LegacyAreaMinute(cur_min))
      {
         const int begin_bar = LegacyFindBar(g_hour_begin, g_min_begin, time[i]);
         const int end_bar   = LegacyFindBar(g_hour_end,   g_min_end,   time[i]);

         if(begin_bar != WRONG_VALUE && end_bar != WRONG_VALUE &&
            begin_bar >= end_bar && begin_bar < rates_total && end_bar >= 0)
         {
            const int hb = LegacyHighest(begin_bar - end_bar + 1, end_bar);
            const int lb = LegacyLowest(begin_bar - end_bar + 1, end_bar);

            if(hb != WRONG_VALUE && lb != WRONG_VALUE &&
               hb >= 0 && hb < rates_total && lb >= 0 && lb < rates_total)
            {
               const double max_price = high[hb];
               const double min_price = low[lb];

               for(int j = end_bar; j >= i; --j)
               {
                  LegacyUpperAreaBuffer[j] = max_price;
                  LegacyLowerAreaBuffer[j] = min_price;
               }
            }
         }
      }
      else
      {
         LegacyUpperAreaBuffer[i] = EMPTY_VALUE;
         LegacyLowerAreaBuffer[i] = EMPTY_VALUE;
      }
   }
}

// -------------------------------------------------------------------
// SESSION CONSTRUCTION
// -------------------------------------------------------------------
void BuildConfiguredTimes(const datetime day,
                          datetime &start_time,
                          datetime &end_time,
                          datetime &area_end_time)
{
   start_time = AtMinuteOfDay(day, (int)g_period_begin_min);
   end_time   = AtMinuteOfDay(day, (int)g_period_end_min);

   if(g_period_end_min < g_period_begin_min)
      end_time += 86400;

   area_end_time = AtMinuteOfDay(day, (int)g_box_end_min);

   // Place area termination after the configured end in civil-time order.
   // This matches the legacy minute-of-day wrap branch when box_end < end.
   while(area_end_time < end_time)
      area_end_time += 86400;
}

//+------------------------------------------------------------------+
bool ResolveContainingBar(const datetime target,
                          int &shift,
                          datetime &bar_open)
{
   shift = WRONG_VALUE;
   bar_open = 0;

   const datetime latest_open = iTime(_Symbol, _Period, 0);
   if(latest_open <= 0)
      return false;

   // If the target lies beyond the currently forming chart candle, its
   // containing source bar does not exist yet. Do not let LegacyBarShift's
   // future-time fallback to shift zero masquerade as a resolved bar.
   if(target >= latest_open + (datetime)g_period_seconds)
      return false;

   shift = LegacyBarShift(_Symbol, _Period, target, false);
   if(shift == WRONG_VALUE || shift < 0)
      return false;

   bar_open = iTime(_Symbol, _Period, shift);
   if(bar_open <= 0)
      return false;

   // A genuine containing bar must actually contain the configured target.
   // This rejects weekend / source-gap fallbacks to some remote prior bar.
   if(!(bar_open <= target &&
        target < bar_open + (datetime)g_period_seconds))
      return false;

   return true;
}

//+------------------------------------------------------------------+
bool RangeContinuity(const datetime start_open,
                     const datetime end_open)
{
   if(start_open <= 0 || end_open <= 0 || end_open < start_open)
      return false;

   const long delta = (long)(end_open - start_open);
   if(delta % g_period_seconds != 0)
      return false;

   const int expected = (int)(delta / g_period_seconds) + 1;
   if(expected <= 0)
      return false;

   datetime bars[];
   ArraySetAsSeries(bars, false);
   const int copied = CopyTime(_Symbol,
                               _Period,
                               start_open,
                               end_open,
                               bars);

   if(copied != expected)
      return false;

   for(int i = 0; i < copied; ++i)
   {
      const datetime expected_open =
         start_open + (datetime)((long)i * g_period_seconds);
      if(bars[i] != expected_open)
         return false;
   }

   return true;
}

//+------------------------------------------------------------------+
int FindSession(const datetime day_start)
{
   for(int i = ArraySize(g_sessions) - 1; i >= 0; --i)
      if(g_sessions[i].day_start == day_start)
         return i;
   return -1;
}

//+------------------------------------------------------------------+
int EnsureSession(const datetime day_start)
{
   int existing = FindSession(day_start);
   if(existing >= 0)
      return existing;

   const int n = ArraySize(g_sessions);
   ArrayResize(g_sessions, n + 1);
   const int idx = n;

   ORSM_SESSION s;
   s.day_start = day_start;
   BuildConfiguredTimes(day_start,
                        s.configured_start,
                        s.configured_end,
                        s.configured_area_end);

   s.actual_start_open   = 0;
   s.actual_end_open     = 0;
   s.freeze_commit       = 0;
   s.actual_area_end_open = 0;
   s.area_close_commit   = 0;

   s.begin_shift = WRONG_VALUE;
   s.end_shift   = WRONG_VALUE;
   s.area_shift  = WRONG_VALUE;

   s.frozen_high = EMPTY_VALUE;
   s.frozen_low  = EMPTY_VALUE;
   s.frozen_geometry_ready = false;

   s.start_resolved   = ResolveContainingBar(s.configured_start,
                                             s.begin_shift,
                                             s.actual_start_open);
   s.end_resolved     = ResolveContainingBar(s.configured_end,
                                             s.end_shift,
                                             s.actual_end_open);
   s.area_resolved    = ResolveContainingBar(s.configured_area_end,
                                             s.area_shift,
                                             s.actual_area_end_open);

   s.start_aligned = s.start_resolved &&
                     (s.actual_start_open == s.configured_start);

   s.range_continuous = false;
   s.evaluable        = true;

   s.running_high = -DBL_MAX;
   s.running_low  = DBL_MAX;
   s.running_has_geometry = false;

   s.upper_extreme = -DBL_MAX;
   s.lower_extreme = DBL_MAX;
   s.extreme_has_geometry = false;
   s.upper_extreme_birth = 0;
   s.lower_extreme_birth = 0;
   s.upper_extreme_age_bars = 0;
   s.lower_extreme_age_bars = 0;
   s.upper_extreme_candidate_id = 0;
   s.lower_extreme_candidate_id = 0;
   s.sentinel_last_committed_bar_open = 0;
   s.sentinel_gap_seen = false;

   if(s.end_resolved)
      s.freeze_commit = s.actual_end_open + (datetime)g_period_seconds;

   if(s.area_resolved)
      s.area_close_commit = s.actual_area_end_open + (datetime)g_period_seconds;

   const bool end_completed =
      s.end_resolved && s.end_shift >= 1;

   if(s.start_resolved && end_completed &&
      s.begin_shift >= s.end_shift)
   {
      const int count = s.begin_shift - s.end_shift + 1;
      const int hb = LegacyHighest(count, s.end_shift);
      const int lb = LegacyLowest(count, s.end_shift);

      if(hb != WRONG_VALUE && lb != WRONG_VALUE)
      {
         s.frozen_high = iHigh(_Symbol, _Period, hb);
         s.frozen_low  = iLow(_Symbol, _Period, lb);
         s.frozen_geometry_ready = true;
      }

      s.range_continuous = RangeContinuity(s.actual_start_open,
                                           s.actual_end_open);
   }

   if(s.start_resolved && InpRequireExactStartAlignment && !s.start_aligned)
      s.evaluable = false;

   if(end_completed && InpRequireRangeContinuity && !s.range_continuous)
      s.evaluable = false;

   if(end_completed && !s.frozen_geometry_ready)
      s.evaluable = false;

   g_sessions[idx] = s;
   return idx;
}

//+------------------------------------------------------------------+
int FindSessionForBar(const datetime bar_open)
{
   const datetime today = DayStart(bar_open);
   const int today_idx = FindSession(today);

   const datetime prev_day = PreviousDayStart(today);
   const int prev_idx = FindSession(prev_day);

   // Only an actually cross-midnight prior session may own a bar on today's
   // civil date before today's configured start.
   if(prev_idx >= 0 &&
      g_sessions[prev_idx].configured_area_end > today &&
      bar_open >= g_sessions[prev_idx].configured_start &&
      bar_open <= g_sessions[prev_idx].configured_area_end)
      return prev_idx;

   return today_idx;
}

//+------------------------------------------------------------------+
void BuildSessionTable(const int rates_total,
                       const datetime &time[])
{
   ArrayResize(g_sessions, 0);

   const datetime cutoff_day =
      DayStart(time[0] - (datetime)((long)InpHistoryDays * 86400));

   int oldest = rates_total - 1;
   for(int i = rates_total - 1; i >= 0; --i)
   {
      if(time[i] >= cutoff_day)
      {
         oldest = i;
         break;
      }
   }

   // Include one civil predecessor so an overnight session that began before
   // the visible cutoff can still own early bars inside the machine window.
   EnsureSession(PreviousDayStart(DayStart(time[oldest])));

   datetime last_day = 0;
   for(int i = oldest; i >= 0 && !IsStopped(); --i)
   {
      const datetime day = DayStart(time[i]);
      if(day != last_day)
      {
         EnsureSession(day);
         last_day = day;
      }
   }
}

// -------------------------------------------------------------------
// MACHINE BUFFER HELPERS
// -------------------------------------------------------------------
void ClearInteractionFields(const int i)
{
   InteractionEligibleBuffer[i] = 0.0;
   LocationBuffer[i]            = EMPTY_VALUE;
   GrammarEventBuffer[i]        = EMPTY_VALUE;
   OutsideRunBuffer[i]          = EMPTY_VALUE;
   FirstOutsideSideBuffer[i]    = EMPTY_VALUE;
   AboveExcursionCountBuffer[i] = EMPTY_VALUE;
   BelowExcursionCountBuffer[i] = EMPTY_VALUE;
   FailedAboveCountBuffer[i]    = EMPTY_VALUE;
   FailedBelowCountBuffer[i]    = EMPTY_VALUE;
}

//+------------------------------------------------------------------+
void ClearMachineFields(const int i)
{
   RangeHighBuffer[i]   = EMPTY_VALUE;
   RangeLowBuffer[i]    = EMPTY_VALUE;
   RangeMidBuffer[i]    = EMPTY_VALUE;
   RangeWidthBuffer[i]  = EMPTY_VALUE;
   LifecycleBuffer[i]   = EMPTY_VALUE;
   RangeOpenBuffer[i]   = 0.0;
   RangeClosedBuffer[i] = 0.0;
   AreaActiveBuffer[i]  = 0.0;

   ClearInteractionFields(i);

   DevelopingHighBuffer[i]     = EMPTY_VALUE;
   DevelopingLowBuffer[i]      = EMPTY_VALUE;
   FreezePendingBuffer[i]      = 0.0;
   LegacyDisplayPhaseBuffer[i] = (double)ORSM_DISPLAY_NONE;
   GeometryKnownBuffer[i]      = 0.0;
   SourceCoverageBuffer[i]     = 0.0;
   ConfigRangeStartBuffer[i]   = EMPTY_VALUE;
   ActualRangeStartBuffer[i]   = EMPTY_VALUE;
   ConfigRangeEndBuffer[i]     = EMPTY_VALUE;
   ActualRangeEndBuffer[i]     = EMPTY_VALUE;
   FreezeCommitBuffer[i]       = EMPTY_VALUE;
   ConfigAreaEndBuffer[i]      = EMPTY_VALUE;
   ActualAreaEndBuffer[i]      = EMPTY_VALUE;
   AreaCloseCommitBuffer[i]    = EMPTY_VALUE;
   SessionIdBuffer[i]          = EMPTY_VALUE;

   UpperExtremeSentinelBuffer[i]  = EMPTY_VALUE;
   LowerExtremeSentinelBuffer[i]  = EMPTY_VALUE;
   UpperExtremeCommittedBuffer[i] = EMPTY_VALUE;
   LowerExtremeCommittedBuffer[i] = EMPTY_VALUE;
   UpperExtremeBirthBuffer[i]      = EMPTY_VALUE;
   LowerExtremeBirthBuffer[i]      = EMPTY_VALUE;
   NewUpperExtremeBuffer[i]        = 0.0;
   NewLowerExtremeBuffer[i]        = 0.0;
   UpperExtremeAgeBuffer[i]        = EMPTY_VALUE;
   LowerExtremeAgeBuffer[i]        = EMPTY_VALUE;
   UpperGivebackBuffer[i]          = EMPTY_VALUE;
   LowerGivebackBuffer[i]          = EMPTY_VALUE;
   UpperExtensionRangeBuffer[i]    = EMPTY_VALUE;
   LowerExtensionRangeBuffer[i]    = EMPTY_VALUE;
   UpperCandidateIdBuffer[i]       = EMPTY_VALUE;
   LowerCandidateIdBuffer[i]       = EMPTY_VALUE;
   SentinelWindowActiveBuffer[i]   = 0.0;
   SentinelCoverageBuffer[i]       = 0.0;
}

//+------------------------------------------------------------------+
void ClearMachineBuffers(const int rates_total)
{
   for(int i = 0; i < rates_total; ++i)
      ClearMachineFields(i);
}

//+------------------------------------------------------------------+
ENUM_ORSM_STATE StateForBar(const ORSM_SESSION &s,
                            const datetime bar_open)
{
   if(!s.evaluable)
      return ORSM_NOT_EVALUABLE;

   // Before the source bar containing the configured start exists, configured
   // civil time remains the only boundary we can safely state.
   if(!s.start_resolved)
      return (bar_open < s.configured_start)
             ? ORSM_WAITING
             : ORSM_NOT_EVALUABLE;

   if(bar_open < s.actual_start_open)
      return ORSM_WAITING;

   if(!s.end_resolved)
      return ORSM_COLLECTING;

   // The actual end bar is still part of the legacy range. It remains
   // COLLECTING / freeze-pending until that candle closes.
   if(bar_open <= s.actual_end_open)
      return ORSM_COLLECTING;

   if(!s.frozen_geometry_ready)
      return ORSM_NOT_EVALUABLE;

   if(!s.area_resolved)
      return ORSM_FROZEN;

   if(bar_open < s.area_close_commit)
      return ORSM_FROZEN;

   return ORSM_COMPLETE;
}

//+------------------------------------------------------------------+
void PublishSessionTimes(const int i, const ORSM_SESSION &s)
{
   ConfigRangeStartBuffer[i] = (double)s.configured_start;
   ConfigRangeEndBuffer[i]   = (double)s.configured_end;
   ConfigAreaEndBuffer[i]    = (double)s.configured_area_end;
   SessionIdBuffer[i]        = (double)s.day_start;

   if(s.start_resolved)
      ActualRangeStartBuffer[i] = (double)s.actual_start_open;

   if(s.end_resolved)
   {
      ActualRangeEndBuffer[i] = (double)s.actual_end_open;
      FreezeCommitBuffer[i]   = (double)s.freeze_commit;
   }

   if(s.area_resolved)
   {
      ActualAreaEndBuffer[i]   = (double)s.actual_area_end_open;
      AreaCloseCommitBuffer[i] = (double)s.area_close_commit;
   }
}

//+------------------------------------------------------------------+
void UpdateRunningGeometry(ORSM_SESSION &s,
                           const datetime bar_open,
                           const double bar_high,
                           const double bar_low)
{
   if(!s.start_resolved)
      return;

   if(bar_open < s.actual_start_open)
      return;

   if(s.end_resolved && bar_open > s.actual_end_open)
      return;

   // If the end bar has not appeared yet, any bar at/after actual start remains
   // part of the still-developing range.
   if(!s.running_has_geometry)
   {
      s.running_high = bar_high;
      s.running_low  = bar_low;
      s.running_has_geometry = true;
   }
   else
   {
      s.running_high = MathMax(s.running_high, bar_high);
      s.running_low  = MathMin(s.running_low,  bar_low);
   }
}

// -------------------------------------------------------------------
// CAUSAL RUNNING-EXTREME SENTINELS
//
// The sentinel is deliberately weaker than a "session high/low" claim.
// At every completed bar it means only:
//   upper = highest causally completed chart-bar high observed so far
//   lower = lowest  causally completed chart-bar low  observed so far
// inside [actual range start, configured/actual area end].
//
// Bar 0 may display a provisional line including the currently forming bar,
// but committed buffers, event flags, candidate ids, birth times, and ages are
// never advanced until that bar completes.
// -------------------------------------------------------------------
bool SentinelWindowEligible(const ORSM_SESSION &s,
                            const datetime bar_open,
                            const datetime bar_close)
{
   if(!InpEnableExtremeSentinels || !s.start_resolved)
      return false;

   if(InpRequireExactStartAlignment && !s.start_aligned)
      return false;

   if(bar_open < s.actual_start_open)
      return false;

   if(s.area_resolved)
      return bar_close <= s.area_close_commit;

   return bar_open <= s.configured_area_end;
}

//+------------------------------------------------------------------+
void PublishCommittedSentinelState(const int i,
                                   const ORSM_SESSION &s,
                                   const double close_price,
                                   const bool geometry_known)
{
   if(!s.extreme_has_geometry || s.sentinel_gap_seen)
      return;

   UpperExtremeCommittedBuffer[i] = s.upper_extreme;
   LowerExtremeCommittedBuffer[i] = s.lower_extreme;
   UpperExtremeBirthBuffer[i]     = (double)s.upper_extreme_birth;
   LowerExtremeBirthBuffer[i]     = (double)s.lower_extreme_birth;
   UpperExtremeAgeBuffer[i]       = (double)s.upper_extreme_age_bars;
   LowerExtremeAgeBuffer[i]       = (double)s.lower_extreme_age_bars;
   UpperCandidateIdBuffer[i]      = (double)s.upper_extreme_candidate_id;
   LowerCandidateIdBuffer[i]      = (double)s.lower_extreme_candidate_id;

   UpperGivebackBuffer[i] = MathMax(0.0, s.upper_extreme - close_price);
   LowerGivebackBuffer[i] = MathMax(0.0, close_price - s.lower_extreme);

   if(geometry_known)
   {
      UpperExtensionRangeBuffer[i] = MathMax(0.0, s.upper_extreme - s.frozen_high);
      LowerExtensionRangeBuffer[i] = MathMax(0.0, s.frozen_low - s.lower_extreme);
   }
}

//+------------------------------------------------------------------+
void ProcessExtremeSentinels(const int i,
                             ORSM_SESSION &s,
                             const datetime bar_open,
                             const double bar_high,
                             const double bar_low,
                             const double close_price,
                             const bool completed,
                             const bool geometry_known)
{
   const datetime bar_close = bar_open + (datetime)g_period_seconds;
   if(!SentinelWindowEligible(s, bar_open, bar_close))
      return;

   SentinelWindowActiveBuffer[i] = 1.0;

   // Once a gap is observed the running extreme can no longer be asserted as
   // the true running path extreme. Fail closed instead of silently bridging it.
   const bool has_prior = (s.sentinel_last_committed_bar_open > 0);
   const bool continuity_ok = !has_prior ||
      (bar_open - s.sentinel_last_committed_bar_open == g_period_seconds);

   if(InpRequireChartContinuity && !continuity_ok)
   {
      if(completed)
         s.sentinel_gap_seen = true;
      return;
   }

   if(s.sentinel_gap_seen)
      return;

   SentinelCoverageBuffer[i] = 1.0;

   if(completed)
   {
      bool new_upper = false;
      bool new_lower = false;

      if(!s.extreme_has_geometry)
      {
         s.upper_extreme = bar_high;
         s.lower_extreme = bar_low;
         s.extreme_has_geometry = true;

         s.upper_extreme_birth = bar_close;
         s.lower_extreme_birth = bar_close;
         s.upper_extreme_age_bars = 0;
         s.lower_extreme_age_bars = 0;
         s.upper_extreme_candidate_id = 1;
         s.lower_extreme_candidate_id = 1;
         new_upper = true;
         new_lower = true;
      }
      else
      {
         if(bar_high > s.upper_extreme)
         {
            s.upper_extreme = bar_high;
            s.upper_extreme_birth = bar_close;
            s.upper_extreme_age_bars = 0;
            s.upper_extreme_candidate_id++;
            new_upper = true;
         }
         else
         {
            s.upper_extreme_age_bars++;
         }

         if(bar_low < s.lower_extreme)
         {
            s.lower_extreme = bar_low;
            s.lower_extreme_birth = bar_close;
            s.lower_extreme_age_bars = 0;
            s.lower_extreme_candidate_id++;
            new_lower = true;
         }
         else
         {
            s.lower_extreme_age_bars++;
         }
      }

      s.sentinel_last_committed_bar_open = bar_open;

      NewUpperExtremeBuffer[i] = new_upper ? 1.0 : 0.0;
      NewLowerExtremeBuffer[i] = new_lower ? 1.0 : 0.0;

      UpperExtremeSentinelBuffer[i] = s.upper_extreme;
      LowerExtremeSentinelBuffer[i] = s.lower_extreme;
      PublishCommittedSentinelState(i, s, close_price, geometry_known);
      return;
   }

   // Forming bar: show what is knowable now without mutating the committed
   // candidate identity. This keeps the line useful live while the machine
   // retains deterministic completed-bar knowledge semantics.
   double live_upper = s.extreme_has_geometry ? s.upper_extreme : bar_high;
   double live_lower = s.extreme_has_geometry ? s.lower_extreme : bar_low;
   live_upper = MathMax(live_upper, bar_high);
   live_lower = MathMin(live_lower, bar_low);

   UpperExtremeSentinelBuffer[i] = live_upper;
   LowerExtremeSentinelBuffer[i] = live_lower;

   PublishCommittedSentinelState(i, s, close_price, geometry_known);

   // Live display measurements follow the provisional line on bar 0. The
   // separate *Committed buffers above remain untouched until bar completion.
   UpperGivebackBuffer[i] = MathMax(0.0, live_upper - close_price);
   LowerGivebackBuffer[i] = MathMax(0.0, close_price - live_lower);

   if(geometry_known)
   {
      UpperExtensionRangeBuffer[i] = MathMax(0.0, live_upper - s.frozen_high);
      LowerExtensionRangeBuffer[i] = MathMax(0.0, s.frozen_low - live_lower);
   }
}

// -------------------------------------------------------------------
// GRAMMAR
// -------------------------------------------------------------------
int FindTrack(const datetime session_id)
{
   for(int i = ArraySize(g_tracks) - 1; i >= 0; --i)
      if(g_tracks[i].session_id == session_id)
         return i;
   return -1;
}

//+------------------------------------------------------------------+
int EnsureTrack(const datetime session_id)
{
   int idx = FindTrack(session_id);
   if(idx >= 0)
      return idx;

   const int n = ArraySize(g_tracks);
   ArrayResize(g_tracks, n + 1);
   idx = n;

   g_tracks[idx].session_id             = session_id;
   g_tracks[idx].previous_location      = ORSM_LOC_NOT_AVAILABLE;
   g_tracks[idx].outside_run_bars       = 0;
   g_tracks[idx].last_eligible_bar_open = 0;
   g_tracks[idx].first_outside_side     = 0;
   g_tracks[idx].above_excursions       = 0;
   g_tracks[idx].below_excursions       = 0;
   g_tracks[idx].failed_above           = 0;
   g_tracks[idx].failed_below           = 0;

   return idx;
}

//+------------------------------------------------------------------+
int ClassifyLocation(const ORSM_SESSION &s, const double close_price)
{
   // Boundary closes remain in-zone.
   if(close_price > s.frozen_high)
      return ORSM_LOC_ABOVE;
   if(close_price < s.frozen_low)
      return ORSM_LOC_BELOW;
   return ORSM_LOC_IN_ZONE;
}

//+------------------------------------------------------------------+
bool InteractionEligible(const ORSM_SESSION &s,
                         const datetime bar_open,
                         const datetime bar_close)
{
   if(!s.evaluable || !s.frozen_geometry_ready || !s.end_resolved)
      return false;

   if(bar_open < s.freeze_commit)
      return false;

   if(s.area_resolved && bar_close > s.area_close_commit)
      return false;

   if(!s.area_resolved && bar_open > s.configured_area_end)
      return false;

   return true;
}

//+------------------------------------------------------------------+
int ResumeEventForLocation(const int location)
{
   if(location == ORSM_LOC_ABOVE)
      return ORSM_EVENT_RESUME_ABOVE;
   if(location == ORSM_LOC_BELOW)
      return ORSM_EVENT_RESUME_BELOW;
   return ORSM_EVENT_RESUME_IN_ZONE;
}

//+------------------------------------------------------------------+
void ProcessGrammar(const int i,
                    ORSM_SESSION &s,
                    const datetime bar_open,
                    const double close_price)
{
   const datetime bar_close = bar_open + (datetime)g_period_seconds;
   if(!InteractionEligible(s, bar_open, bar_close))
      return;

   InteractionEligibleBuffer[i] = 1.0;

   const int tidx = EnsureTrack(s.day_start);
   const int location = ClassifyLocation(s, close_price);

   int event = ORSM_EVENT_NONE;

   const bool has_predecessor =
      (g_tracks[tidx].last_eligible_bar_open > 0);

   const bool continuous =
      has_predecessor &&
      (bar_open - g_tracks[tidx].last_eligible_bar_open == g_period_seconds);

   if(has_predecessor && InpRequireChartContinuity && !continuous)
   {
      event = ResumeEventForLocation(location);
      g_tracks[tidx].previous_location = ORSM_LOC_NOT_AVAILABLE;
      g_tracks[tidx].outside_run_bars  = 0;
   }

   const int previous = g_tracks[tidx].previous_location;

   if(event == ORSM_EVENT_NONE)
   {
      if(location == ORSM_LOC_IN_ZONE)
      {
         if(previous == ORSM_LOC_ABOVE)
         {
            if(g_tracks[tidx].outside_run_bars == 1)
            {
               event = ORSM_EVENT_FAILED_ABOVE;
               g_tracks[tidx].failed_above++;
            }
            else
               event = ORSM_EVENT_RETURN_FROM_ABOVE;
         }
         else if(previous == ORSM_LOC_BELOW)
         {
            if(g_tracks[tidx].outside_run_bars == 1)
            {
               event = ORSM_EVENT_FAILED_BELOW;
               g_tracks[tidx].failed_below++;
            }
            else
               event = ORSM_EVENT_RETURN_FROM_BELOW;
         }
         else
            event = ORSM_EVENT_IN_ZONE;
      }
      else if(location == ORSM_LOC_ABOVE)
      {
         if(previous == ORSM_LOC_ABOVE)
            event = ORSM_EVENT_PERSIST_ABOVE;
         else if(previous == ORSM_LOC_BELOW)
         {
            event = ORSM_EVENT_CROSS_BELOW_TO_ABOVE;
            g_tracks[tidx].above_excursions++;
         }
         else
         {
            event = ORSM_EVENT_FIRST_CLOSE_ABOVE;
            g_tracks[tidx].above_excursions++;
         }

         if(g_tracks[tidx].first_outside_side == 0)
            g_tracks[tidx].first_outside_side = +1;
      }
      else if(location == ORSM_LOC_BELOW)
      {
         if(previous == ORSM_LOC_BELOW)
            event = ORSM_EVENT_PERSIST_BELOW;
         else if(previous == ORSM_LOC_ABOVE)
         {
            event = ORSM_EVENT_CROSS_ABOVE_TO_BELOW;
            g_tracks[tidx].below_excursions++;
         }
         else
         {
            event = ORSM_EVENT_FIRST_CLOSE_BELOW;
            g_tracks[tidx].below_excursions++;
         }

         if(g_tracks[tidx].first_outside_side == 0)
            g_tracks[tidx].first_outside_side = -1;
      }
   }
   else
   {
      // After an observation gap, begin a new observed outside segment without
      // inventing the unseen transition that occurred inside the gap.
      if(location == ORSM_LOC_ABOVE)
      {
         g_tracks[tidx].above_excursions++;
         if(g_tracks[tidx].first_outside_side == 0)
            g_tracks[tidx].first_outside_side = +1;
      }
      else if(location == ORSM_LOC_BELOW)
      {
         g_tracks[tidx].below_excursions++;
         if(g_tracks[tidx].first_outside_side == 0)
            g_tracks[tidx].first_outside_side = -1;
      }
   }

   if(location == ORSM_LOC_IN_ZONE)
   {
      g_tracks[tidx].outside_run_bars = 0;
   }
   else if(location == previous &&
           previous != ORSM_LOC_NOT_AVAILABLE &&
           (continuous || !InpRequireChartContinuity))
   {
      g_tracks[tidx].outside_run_bars++;
   }
   else
   {
      g_tracks[tidx].outside_run_bars = 1;
   }

   g_tracks[tidx].previous_location = location;
   g_tracks[tidx].last_eligible_bar_open = bar_open;

   LocationBuffer[i]            = (double)location;
   GrammarEventBuffer[i]        = (double)event;
   OutsideRunBuffer[i]          = (double)g_tracks[tidx].outside_run_bars;
   FirstOutsideSideBuffer[i]    = (double)g_tracks[tidx].first_outside_side;
   AboveExcursionCountBuffer[i] = (double)g_tracks[tidx].above_excursions;
   BelowExcursionCountBuffer[i] = (double)g_tracks[tidx].below_excursions;
   FailedAboveCountBuffer[i]    = (double)g_tracks[tidx].failed_above;
   FailedBelowCountBuffer[i]    = (double)g_tracks[tidx].failed_below;
}

// -------------------------------------------------------------------
// MACHINE PROCESSING
// -------------------------------------------------------------------
void PublishMachineBar(const int i,
                       const datetime bar_open,
                       const double bar_high,
                       const double bar_low,
                       const double close_price,
                       const bool completed)
{
   ClearMachineFields(i);
   LegacyDisplayPhaseBuffer[i] = (double)LegacyDisplayPhaseAt(bar_open);

   const int sidx = FindSessionForBar(bar_open);
   if(sidx < 0)
      return;

   ORSM_SESSION s = g_sessions[sidx];
   PublishSessionTimes(i, s);

   // Running geometry is updated only by bars that belong to the actual source
   // range. The current forming bar may contribute to DevelopingHigh/Low but
   // never to final geometry until its close has been observed on a later bar.
   if(s.start_resolved &&
      bar_open >= s.actual_start_open &&
      (!s.end_resolved || bar_open <= s.actual_end_open))
   {
      double dev_high = s.running_has_geometry ? s.running_high : bar_high;
      double dev_low  = s.running_has_geometry ? s.running_low  : bar_low;

      dev_high = MathMax(dev_high, bar_high);
      dev_low  = MathMin(dev_low,  bar_low);

      DevelopingHighBuffer[i] = dev_high;
      DevelopingLowBuffer[i]  = dev_low;

      if(completed)
         UpdateRunningGeometry(s, bar_open, bar_high, bar_low);
   }

   ENUM_ORSM_STATE state = StateForBar(s, bar_open);
   LifecycleBuffer[i] = (double)state;

   const bool end_bar_active =
      s.end_resolved && bar_open == s.actual_end_open;

   if(state == ORSM_COLLECTING)
      RangeOpenBuffer[i] = 1.0;

   if(end_bar_active)
      FreezePendingBuffer[i] = 1.0;

   const bool geometry_known =
      s.evaluable &&
      s.frozen_geometry_ready &&
      s.freeze_commit > 0 &&
      bar_open >= s.freeze_commit;

   if(geometry_known)
   {
      GeometryKnownBuffer[i] = 1.0;
      RangeClosedBuffer[i]   = 1.0;

      RangeHighBuffer[i]  = s.frozen_high;
      RangeLowBuffer[i]   = s.frozen_low;
      RangeMidBuffer[i]   = 0.5 * (s.frozen_high + s.frozen_low);
      RangeWidthBuffer[i] = s.frozen_high - s.frozen_low;
   }

   const bool range_source_qualified =
      s.start_resolved &&
      s.end_resolved &&
      s.frozen_geometry_ready &&
      (!InpRequireExactStartAlignment || s.start_aligned) &&
      (!InpRequireRangeContinuity || s.range_continuous);

   SourceCoverageBuffer[i] = range_source_qualified ? 1.0 : 0.0;

   if(geometry_known)
   {
      if(s.area_resolved)
      {
         if(bar_open < s.area_close_commit)
            AreaActiveBuffer[i] = 1.0;
      }
      else if(bar_open <= s.configured_area_end)
      {
         AreaActiveBuffer[i] = 1.0;
      }
   }

   ProcessExtremeSentinels(i,
                           s,
                           bar_open,
                           bar_high,
                           bar_low,
                           close_price,
                           completed,
                           geometry_known);

   if(completed)
   {
      ProcessGrammar(i, s, bar_open, close_price);
      g_sessions[sidx] = s;
   }
}

//+------------------------------------------------------------------+
int MachineOldestIndex(const int rates_total,
                       const datetime &time[])
{
   const datetime cutoff_day =
      DayStart(time[0] - (datetime)((long)InpHistoryDays * 86400));

   int oldest = rates_total - 1;
   for(int i = rates_total - 1; i >= 0; --i)
   {
      if(time[i] >= cutoff_day)
      {
         oldest = i;
         break;
      }
   }
   return oldest;
}

//+------------------------------------------------------------------+
void RebuildMachineHistory(const int rates_total,
                           const datetime &time[],
                           const double &high[],
                           const double &low[],
                           const double &close[])
{
   ClearMachineBuffers(rates_total);
   BuildSessionTable(rates_total, time);
   ArrayResize(g_tracks, 0);

   const int oldest = MachineOldestIndex(rates_total, time);

   // Oldest -> newest, completed candles only for grammar transitions.
   for(int i = oldest; i >= 1 && !IsStopped(); --i)
      PublishMachineBar(i, time[i], high[i], low[i], close[i], true);

   // Current bar receives live causal metadata/developing geometry only.
   PublishMachineBar(0, time[0], high[0], low[0], close[0], false);

   g_last_machine_bar0 = time[0];
}

//+------------------------------------------------------------------+
void RefreshCurrentMachineBar(const datetime &time[],
                              const double &high[],
                              const double &low[],
                              const double &close[])
{
   // Do not mutate persistent running geometry with the forming bar. The next
   // full rebuild occurs when this candle becomes completed.
   PublishMachineBar(0, time[0], high[0], low[0], close[0], false);
}

//+------------------------------------------------------------------+
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
   if(rates_total < 4)
      return 0;

   ArraySetAsSeries(time, true);
   ArraySetAsSeries(high, true);
   ArraySetAsSeries(low, true);
   ArraySetAsSeries(close, true);

   // 1) Exact legacy compatibility output. This intentionally updates on every
   // tick because the recovered Breakout source does so.
   CalculateLegacyBuffers(rates_total,
                          prev_calculated,
                          time,
                          high,
                          low);

   // 2) Explicit causal machine + grammar. Full reconstruction only on first
   // attach/history reset or when a new chart candle appears.
   const bool rebuild_machine =
      (prev_calculated == 0 ||
       g_last_machine_bar0 == 0 ||
       time[0] != g_last_machine_bar0);

   if(rebuild_machine)
      RebuildMachineHistory(rates_total, time, high, low, close);
   else
      RefreshCurrentMachineBar(time, high, low, close);

   return rates_total;
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   // Buffer-rendered legacy and sentinel lines require no chart-object cleanup.
}
//+------------------------------------------------------------------+
