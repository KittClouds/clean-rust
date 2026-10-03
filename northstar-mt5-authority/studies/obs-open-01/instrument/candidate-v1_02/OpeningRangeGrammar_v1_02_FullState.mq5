//+------------------------------------------------------------------+
//|              OpeningRangeGrammar_v1_02_FullState.mq5             |
//| Trade-agnostic causal opening-range + interaction observer        |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026, Indices Group (Pty) Ltd"
#property version   "1.02"
#property description "Trade-agnostic opening-range and post-freeze interaction grammar."
#property description "M1 owns range geometry; chart timeframe owns completed-candle interaction grammar."
#property description "Full machine state is exposed through DRAW_NONE Data Window / iCustom buffers."

#property indicator_chart_window
#property indicator_buffers 17
#property indicator_plots   17

// -------------------------------------------------------------------
// CLOCK CONTRACT
// All times are broker/server chart time. No timezone inference.
// -------------------------------------------------------------------
input group "Opening Range Clock"
input int    InpStartHour          = 9;
input int    InpStartMinute        = 30;
input int    InpRangeMinutes       = 5;       // science sweep: 1..30
input int    InpAreaEndHour        = 16;      // post-range observation area ends here
input int    InpAreaEndMinute      = 0;
input int    InpHistoryDays        = 20;

input group "Coverage Contract"
input bool   InpRequireEveryM1Bar  = true;    // missing source minute => NOT_EVALUABLE
input bool   InpRequireChartContinuity = true;// transition grammar never bridges missing chart bars

input group "Original-Style Drawing"
input bool   InpShowRangeArea      = true;
input bool   InpShowPostRangeArea  = true;
input bool   InpShowMidline        = false;
input bool   InpShowLabels         = true;
input color  InpRangeColor         = clrRed;
input color  InpExtensionColor     = clrViolet;
input color  InpMidColor           = clrMediumPurple;
input int    InpRangeAlpha         = 32;
input int    InpExtensionAlpha     = 12;
input int    InpRailWidth          = 1;
input ENUM_LINE_STYLE InpRailStyle = STYLE_SOLID;
input string InpUniqueId           = "01";

// -------------------------------------------------------------------
// BUFFER CONTRACT — all 17 are visible in Data Window and via iCustom.
//
//  0 RangeHigh
//  1 RangeLow
//  2 RangeMid
//  3 RangeWidth
//  4 LifecycleState
//  5 RangeOpenFlag
//  6 RangeClosedFlag
//  7 AreaActiveFlag
//  8 InteractionEligible
//  9 LocationState
// 10 GrammarEvent
// 11 OutsideRunBars
// 12 FirstOutsideSide        (+1 above, -1 below, 0 none observed)
// 13 AboveExcursionCount
// 14 BelowExcursionCount
// 15 FailedAboveCount
// 16 FailedBelowCount
//
// Final range geometry is NEVER emitted before range_end.
// Interaction grammar uses completed chart candles only.
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

enum ENUM_ORG_STATE
{
   ORG_NOT_EVALUABLE = -1,
   ORG_WAITING       = 0,
   ORG_COLLECTING    = 1,
   ORG_FROZEN        = 2,
   ORG_COMPLETE      = 3
};

// Persistent topological location of a completed eligible candle.
enum ENUM_ORG_LOCATION
{
   ORG_LOC_NOT_AVAILABLE = 0,
   ORG_LOC_IN_ZONE       = 1,
   ORG_LOC_ABOVE         = 2,
   ORG_LOC_BELOW         = 3
};

// One-bar observational grammar.
//
// FAILED_ABOVE is STRICT:
//   previous completed eligible candle closed ABOVE,
//   that above run contained exactly one observed candle,
//   current completed eligible candle closes IN_ZONE.
//
// FAILED_BELOW is the exact mirror.
//
// RETURN_FROM_* is a return after 2+ consecutive observed outside closes.
//
// "FIRST_CLOSE" means first close in that outside segment. It deliberately
// does NOT claim an order-flow mechanism, breakout success, or tradability.
enum ENUM_ORG_EVENT
{
   ORG_EVENT_NONE                    = 0,
   ORG_EVENT_IN_ZONE                 = 1,

   ORG_EVENT_FIRST_CLOSE_ABOVE       = 2,
   ORG_EVENT_PERSIST_ABOVE           = 3,
   ORG_EVENT_FAILED_ABOVE            = 4,
   ORG_EVENT_RETURN_FROM_ABOVE       = 5,

   ORG_EVENT_FIRST_CLOSE_BELOW       = 6,
   ORG_EVENT_PERSIST_BELOW           = 7,
   ORG_EVENT_FAILED_BELOW            = 8,
   ORG_EVENT_RETURN_FROM_BELOW       = 9,

   ORG_EVENT_CROSS_ABOVE_TO_BELOW    = 10,
   ORG_EVENT_CROSS_BELOW_TO_ABOVE    = 11,

   // Explicit continuity states: after missing chart candles, no transition
   // across the unseen interval is inferred.
   ORG_EVENT_RESUME_IN_ZONE          = 12,
   ORG_EVENT_RESUME_ABOVE            = 13,
   ORG_EVENT_RESUME_BELOW            = 14
};

struct ORG_SESSION
{
   datetime day_start;
   datetime range_start;
   datetime range_end;
   datetime area_end;

   double   high;
   double   low;
   int      closed_m1_bars;
   int      expected_m1_bars;

   ENUM_ORG_STATE state;
   bool     has_geometry;
   bool     evaluable;
};

struct ORG_RENDER_RECEIPT
{
   datetime day_start;
   double   high;
   double   low;
   int      closed_m1_bars;
   ENUM_ORG_STATE state;
   bool     has_geometry;
   bool     evaluable;
};

struct ORG_INTERACTION_TRACK
{
   datetime day_start;
   int      previous_location;
   int      outside_run_bars;
   datetime last_eligible_bar_open;

   int      first_outside_side;
   int      above_excursions;
   int      below_excursions;
   int      failed_above;
   int      failed_below;
};

ORG_SESSION           g_sessions[];
ORG_RENDER_RECEIPT    g_rendered[];
ORG_INTERACTION_TRACK g_tracks[];

string   g_prefix = "";
datetime g_lastClosedM1 = 0;
datetime g_lastProcessedChartBar = 0;

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
datetime AtMinuteOfDay(const datetime day_start,
                       const int hour,
                       const int minute)
{
   return day_start + (datetime)(hour * 3600 + minute * 60);
}

//+------------------------------------------------------------------+
string DayKey(const datetime day_start)
{
   MqlDateTime s;
   TimeToStruct(day_start, s);
   return StringFormat("%04d%02d%02d", s.year, s.mon, s.day);
}

//+------------------------------------------------------------------+
string StateText(const ENUM_ORG_STATE state)
{
   switch(state)
   {
      case ORG_NOT_EVALUABLE: return "NOT_EVALUABLE";
      case ORG_WAITING:       return "WAITING";
      case ORG_COLLECTING:    return "COLLECTING";
      case ORG_FROZEN:        return "FROZEN";
      case ORG_COMPLETE:      return "COMPLETE";
   }
   return "UNKNOWN";
}

//+------------------------------------------------------------------+
string ZoneChartText(const ORG_SESSION &s)
{
   if(!s.evaluable && s.state == ORG_NOT_EVALUABLE)
      return "NOT_EVALUABLE";

   if(s.state == ORG_COLLECTING)
      return "OPEN";

   if(s.state == ORG_FROZEN || s.state == ORG_COMPLETE)
      return "CLOSED";

   return StateText(s.state);
}

//+------------------------------------------------------------------+
void ConfigureDataPlot(const int index, const string label)
{
   PlotIndexSetInteger(index, PLOT_DRAW_TYPE, DRAW_NONE);
   PlotIndexSetInteger(index, PLOT_SHOW_DATA, true);
   PlotIndexSetString(index, PLOT_LABEL, label);
}

//+------------------------------------------------------------------+
bool ValidateInputs()
{
   if(InpStartHour < 0 || InpStartHour > 23 ||
      InpAreaEndHour < 0 || InpAreaEndHour > 23 ||
      InpStartMinute < 0 || InpStartMinute > 59 ||
      InpAreaEndMinute < 0 || InpAreaEndMinute > 59 ||
      InpRangeMinutes < 1 || InpRangeMinutes > 1440 ||
      InpHistoryDays < 1 || InpHistoryDays > 365 ||
      InpRangeAlpha < 0 || InpRangeAlpha > 255 ||
      InpExtensionAlpha < 0 || InpExtensionAlpha > 255 ||
      InpRailWidth < 1 || InpRailWidth > 5)
      return false;

   const int startMinute = InpStartHour * 60 + InpStartMinute;
   const int areaMinute  = InpAreaEndHour * 60 + InpAreaEndMinute;

   // V1 deliberately refuses ambiguous overnight sessions.
   if(areaMinute <= startMinute)
      return false;

   if(startMinute + InpRangeMinutes > areaMinute)
      return false;

   if(PeriodSeconds(_Period) <= 0)
      return false;

   return true;
}

//+------------------------------------------------------------------+
int OnInit()
{
   if(!ValidateInputs())
   {
      Print("OpeningRangeGrammar: invalid clock/drawing/timeframe inputs.");
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

   ConfigureDataPlot(0,  "Range High");
   ConfigureDataPlot(1,  "Range Low");
   ConfigureDataPlot(2,  "Range Mid");
   ConfigureDataPlot(3,  "Range Width");
   ConfigureDataPlot(4,  "Lifecycle State");
   ConfigureDataPlot(5,  "Range Open");
   ConfigureDataPlot(6,  "Range Closed");
   ConfigureDataPlot(7,  "Area Active");
   ConfigureDataPlot(8,  "Interaction Eligible");
   ConfigureDataPlot(9,  "Location State");
   ConfigureDataPlot(10, "Grammar Event");
   ConfigureDataPlot(11, "Outside Run Bars");
   ConfigureDataPlot(12, "First Outside Side");
   ConfigureDataPlot(13, "Above Excursion Count");
   ConfigureDataPlot(14, "Below Excursion Count");
   ConfigureDataPlot(15, "Failed Above Count");
   ConfigureDataPlot(16, "Failed Below Count");

   g_prefix = "ORG_" + SanitizeId(InpUniqueId) + "_";

   IndicatorSetString(
      INDICATOR_SHORTNAME,
      "Opening Range Grammar FullState " +
      IntegerToString(InpRangeMinutes) +
      "m [" + InpUniqueId + "]");

   IndicatorSetInteger(INDICATOR_DIGITS, _Digits);

   ObjectsDeleteAll(0, g_prefix);
   ArrayResize(g_sessions, 0);
   ArrayResize(g_rendered, 0);
   ArrayResize(g_tracks, 0);
   g_lastClosedM1 = 0;
   g_lastProcessedChartBar = 0;

   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
int FindSession(const datetime day)
{
   for(int i = ArraySize(g_sessions) - 1; i >= 0; --i)
      if(g_sessions[i].day_start == day)
         return i;
   return -1;
}

//+------------------------------------------------------------------+
int EnsureSession(const datetime day)
{
   int idx = FindSession(day);
   if(idx >= 0)
      return idx;

   const int n = ArraySize(g_sessions);
   ArrayResize(g_sessions, n + 1);
   idx = n;

   g_sessions[idx].day_start        = day;
   g_sessions[idx].range_start      =
      AtMinuteOfDay(day, InpStartHour, InpStartMinute);
   g_sessions[idx].range_end        =
      g_sessions[idx].range_start +
      (datetime)(InpRangeMinutes * 60);
   g_sessions[idx].area_end         =
      AtMinuteOfDay(day, InpAreaEndHour, InpAreaEndMinute);

   g_sessions[idx].high             = -DBL_MAX;
   g_sessions[idx].low              = DBL_MAX;
   g_sessions[idx].closed_m1_bars   = 0;
   g_sessions[idx].expected_m1_bars = InpRangeMinutes;
   g_sessions[idx].state            = ORG_WAITING;
   g_sessions[idx].has_geometry     = false;
   g_sessions[idx].evaluable        = true;

   return idx;
}

//+------------------------------------------------------------------+
void ProcessClosedM1(const MqlRates &bar)
{
   const datetime day = DayStart(bar.time);
   const datetime rs  =
      AtMinuteOfDay(day, InpStartHour, InpStartMinute);
   const datetime re  =
      rs + (datetime)(InpRangeMinutes * 60);
   const datetime ae  =
      AtMinuteOfDay(day, InpAreaEndHour, InpAreaEndMinute);

   if(bar.time < rs || bar.time >= ae)
      return;

   const int idx = EnsureSession(day);

   if(bar.time >= rs && bar.time < re)
   {
      if(!g_sessions[idx].has_geometry)
      {
         g_sessions[idx].high = bar.high;
         g_sessions[idx].low  = bar.low;
         g_sessions[idx].has_geometry = true;
      }
      else
      {
         g_sessions[idx].high =
            MathMax(g_sessions[idx].high, bar.high);
         g_sessions[idx].low =
            MathMin(g_sessions[idx].low, bar.low);
      }

      g_sessions[idx].closed_m1_bars++;
   }
}

//+------------------------------------------------------------------+
void UpdateStates(const datetime now)
{
   for(int i = 0; i < ArraySize(g_sessions); ++i)
   {
      if(now < g_sessions[i].range_start)
      {
         g_sessions[i].state = ORG_WAITING;
         continue;
      }

      if(now < g_sessions[i].range_end)
      {
         g_sessions[i].state = ORG_COLLECTING;
         continue;
      }

      const bool fullCoverage =
         g_sessions[i].has_geometry &&
         (!InpRequireEveryM1Bar ||
          g_sessions[i].closed_m1_bars ==
          g_sessions[i].expected_m1_bars);

      if(!fullCoverage)
      {
         g_sessions[i].evaluable = false;
         g_sessions[i].state = ORG_NOT_EVALUABLE;
         continue;
      }

      g_sessions[i].evaluable = true;
      g_sessions[i].state =
         (now < g_sessions[i].area_end)
         ? ORG_FROZEN
         : ORG_COMPLETE;
   }
}

//+------------------------------------------------------------------+
void TrimSessions(const datetime now)
{
   const datetime cutoff =
      DayStart(now) - (datetime)((InpHistoryDays + 2) * 86400);

   int firstKeep = 0;

   while(firstKeep < ArraySize(g_sessions) &&
         g_sessions[firstKeep].day_start < cutoff)
      ++firstKeep;

   if(firstKeep <= 0)
      return;

   const int keep = ArraySize(g_sessions) - firstKeep;

   ORG_SESSION tmp[];
   ArrayResize(tmp, keep);

   for(int i = 0; i < keep; ++i)
      tmp[i] = g_sessions[firstKeep + i];

   ArrayResize(g_sessions, keep);

   for(int i = 0; i < keep; ++i)
      g_sessions[i] = tmp[i];
}

//+------------------------------------------------------------------+
bool BuildInitialHistory(const datetime now)
{
   const datetime today = DayStart(now);
   const datetime from =
      today - (datetime)((InpHistoryDays + 3) * 86400);

   MqlRates m1[];
   ArraySetAsSeries(m1, false);

   const int copied =
      CopyRates(_Symbol, PERIOD_M1, from, now, m1);

   if(copied <= 0)
      return false;

   ArrayResize(g_sessions, 0);
   g_lastClosedM1 = 0;

   for(int i = 0; i < copied && !IsStopped(); ++i)
   {
      if(m1[i].time + 60 > now)
         continue;

      ProcessClosedM1(m1[i]);
      g_lastClosedM1 = m1[i].time;
   }

   // Make the live daily lifecycle explicit even before the first range
   // minute has closed.
   EnsureSession(DayStart(now));

   TrimSessions(now);
   UpdateStates(now);

   return true;
}

//+------------------------------------------------------------------+
bool UpdateNewClosedM1(const datetime now)
{
   const datetime latestClosed =
      iTime(_Symbol, PERIOD_M1, 1);

   if(latestClosed <= 0)
      return false;

   if(g_lastClosedM1 == 0)
      return BuildInitialHistory(now);

   if(latestClosed == g_lastClosedM1)
   {
      UpdateStates(now);
      return false;
   }

   MqlRates fresh[];
   ArraySetAsSeries(fresh, false);

   const datetime from =
      g_lastClosedM1 + 60;

   const int copied =
      CopyRates(_Symbol, PERIOD_M1, from, latestClosed, fresh);

   if(copied <= 0)
   {
      // Never silently skip source minutes.
      return BuildInitialHistory(now);
   }

   for(int i = 0; i < copied && !IsStopped(); ++i)
   {
      if(fresh[i].time <= g_lastClosedM1)
         continue;

      if(fresh[i].time > latestClosed)
         continue;

      ProcessClosedM1(fresh[i]);
      g_lastClosedM1 = fresh[i].time;
   }

   EnsureSession(DayStart(now));
   TrimSessions(now);
   UpdateStates(now);

   return true;
}

//+------------------------------------------------------------------+
ENUM_ORG_STATE LifecycleAt(const ORG_SESSION &s,
                           const datetime bar_open)
{
   if(bar_open < s.range_start)
      return ORG_WAITING;

   if(bar_open < s.range_end)
      return ORG_COLLECTING;

   if(!s.evaluable)
      return ORG_NOT_EVALUABLE;

   if(bar_open < s.area_end)
      return ORG_FROZEN;

   return ORG_COMPLETE;
}

//+------------------------------------------------------------------+
void ClearInteractionFields(const int index)
{
   InteractionEligibleBuffer[index] = 0.0;
   LocationBuffer[index]            = EMPTY_VALUE;
   GrammarEventBuffer[index]        = EMPTY_VALUE;
   OutsideRunBuffer[index]          = EMPTY_VALUE;
   FirstOutsideSideBuffer[index]    = EMPTY_VALUE;
   AboveExcursionCountBuffer[index] = EMPTY_VALUE;
   BelowExcursionCountBuffer[index] = EMPTY_VALUE;
   FailedAboveCountBuffer[index]    = EMPTY_VALUE;
   FailedBelowCountBuffer[index]    = EMPTY_VALUE;
}

//+------------------------------------------------------------------+
void PublishBaseFields(const int index,
                       const datetime bar_open)
{
   RangeHighBuffer[index]   = EMPTY_VALUE;
   RangeLowBuffer[index]    = EMPTY_VALUE;
   RangeMidBuffer[index]    = EMPTY_VALUE;
   RangeWidthBuffer[index]  = EMPTY_VALUE;
   LifecycleBuffer[index]   = EMPTY_VALUE;
   RangeOpenBuffer[index]   = 0.0;
   RangeClosedBuffer[index] = 0.0;
   AreaActiveBuffer[index]  = 0.0;

   ClearInteractionFields(index);

   const int sidx =
      FindSession(DayStart(bar_open));

   if(sidx < 0)
      return;

   const ENUM_ORG_STATE lifecycle =
      LifecycleAt(g_sessions[sidx], bar_open);

   LifecycleBuffer[index] =
      (double)lifecycle;

   if(lifecycle == ORG_COLLECTING)
      RangeOpenBuffer[index] = 1.0;

   if(g_sessions[sidx].evaluable &&
      (lifecycle == ORG_FROZEN ||
       lifecycle == ORG_COMPLETE))
   {
      RangeClosedBuffer[index] = 1.0;

      RangeHighBuffer[index] =
         g_sessions[sidx].high;
      RangeLowBuffer[index] =
         g_sessions[sidx].low;
      RangeMidBuffer[index] =
         0.5 *
         (g_sessions[sidx].high + g_sessions[sidx].low);
      RangeWidthBuffer[index] =
         g_sessions[sidx].high - g_sessions[sidx].low;
   }

   if(g_sessions[sidx].evaluable &&
      lifecycle == ORG_FROZEN)
      AreaActiveBuffer[index] = 1.0;
}

//+------------------------------------------------------------------+
int FindTrack(const datetime day)
{
   for(int i = ArraySize(g_tracks) - 1; i >= 0; --i)
      if(g_tracks[i].day_start == day)
         return i;

   return -1;
}

//+------------------------------------------------------------------+
int EnsureTrack(const datetime day)
{
   int idx = FindTrack(day);

   if(idx >= 0)
      return idx;

   const int n = ArraySize(g_tracks);
   ArrayResize(g_tracks, n + 1);
   idx = n;

   g_tracks[idx].day_start              = day;
   g_tracks[idx].previous_location      = ORG_LOC_NOT_AVAILABLE;
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
int ClassifyLocation(const ORG_SESSION &s,
                     const double bar_close)
{
   // Boundary closes remain IN_ZONE.
   if(bar_close > s.high)
      return ORG_LOC_ABOVE;

   if(bar_close < s.low)
      return ORG_LOC_BELOW;

   return ORG_LOC_IN_ZONE;
}

//+------------------------------------------------------------------+
bool IsInteractionEligible(const ORG_SESSION &s,
                           const datetime bar_open,
                           const datetime bar_close)
{
   if(!s.evaluable)
      return false;

   // The entire observation candle must begin after the range is frozen
   // and must finish no later than area termination. No mixed candle.
   if(bar_open < s.range_end)
      return false;

   if(bar_close > s.area_end)
      return false;

   return true;
}

//+------------------------------------------------------------------+
int ResumeEventForLocation(const int location)
{
   if(location == ORG_LOC_ABOVE)
      return ORG_EVENT_RESUME_ABOVE;

   if(location == ORG_LOC_BELOW)
      return ORG_EVENT_RESUME_BELOW;

   return ORG_EVENT_RESUME_IN_ZONE;
}

//+------------------------------------------------------------------+
void ProcessInteractionBar(const int index,
                           const datetime bar_open,
                           const double bar_close_price)
{
   PublishBaseFields(index, bar_open);

   const int sidx =
      FindSession(DayStart(bar_open));

   if(sidx < 0)
      return;

   const int period_seconds =
      PeriodSeconds(_Period);

   const datetime bar_close =
      bar_open + (datetime)period_seconds;

   if(!IsInteractionEligible(
         g_sessions[sidx], bar_open, bar_close))
      return;

   InteractionEligibleBuffer[index] = 1.0;

   const int tidx =
      EnsureTrack(g_sessions[sidx].day_start);

   const int location =
      ClassifyLocation(g_sessions[sidx],
                       bar_close_price);

   int event = ORG_EVENT_NONE;

   const bool has_predecessor =
      (g_tracks[tidx].last_eligible_bar_open > 0);

   const bool continuous =
      has_predecessor &&
      (bar_open -
       g_tracks[tidx].last_eligible_bar_open ==
       period_seconds);

   if(has_predecessor &&
      InpRequireChartContinuity &&
      !continuous)
   {
      // Observation resumed after a gap. Preserve counters, but never infer
      // the unseen transition across the missing interval.
      event =
         ResumeEventForLocation(location);

      g_tracks[tidx].previous_location =
         ORG_LOC_NOT_AVAILABLE;

      g_tracks[tidx].outside_run_bars = 0;
   }

   const int previous =
      g_tracks[tidx].previous_location;

   if(event == ORG_EVENT_NONE)
   {
      if(location == ORG_LOC_IN_ZONE)
      {
         if(previous == ORG_LOC_ABOVE)
         {
            if(g_tracks[tidx].outside_run_bars == 1)
            {
               event = ORG_EVENT_FAILED_ABOVE;
               g_tracks[tidx].failed_above++;
            }
            else
               event = ORG_EVENT_RETURN_FROM_ABOVE;
         }
         else if(previous == ORG_LOC_BELOW)
         {
            if(g_tracks[tidx].outside_run_bars == 1)
            {
               event = ORG_EVENT_FAILED_BELOW;
               g_tracks[tidx].failed_below++;
            }
            else
               event = ORG_EVENT_RETURN_FROM_BELOW;
         }
         else
            event = ORG_EVENT_IN_ZONE;
      }
      else if(location == ORG_LOC_ABOVE)
      {
         if(previous == ORG_LOC_ABOVE)
         {
            event = ORG_EVENT_PERSIST_ABOVE;
         }
         else if(previous == ORG_LOC_BELOW)
         {
            event = ORG_EVENT_CROSS_BELOW_TO_ABOVE;
            g_tracks[tidx].above_excursions++;
         }
         else
         {
            event = ORG_EVENT_FIRST_CLOSE_ABOVE;
            g_tracks[tidx].above_excursions++;
         }

         if(g_tracks[tidx].first_outside_side == 0)
            g_tracks[tidx].first_outside_side = +1;
      }
      else if(location == ORG_LOC_BELOW)
      {
         if(previous == ORG_LOC_BELOW)
         {
            event = ORG_EVENT_PERSIST_BELOW;
         }
         else if(previous == ORG_LOC_ABOVE)
         {
            event = ORG_EVENT_CROSS_ABOVE_TO_BELOW;
            g_tracks[tidx].below_excursions++;
         }
         else
         {
            event = ORG_EVENT_FIRST_CLOSE_BELOW;
            g_tracks[tidx].below_excursions++;
         }

         if(g_tracks[tidx].first_outside_side == 0)
            g_tracks[tidx].first_outside_side = -1;
      }
   }
   else
   {
      // A resumed outside observation begins a new OBSERVED segment, while
      // explicitly refusing to claim how it began in the unseen interval.
      if(location == ORG_LOC_ABOVE)
      {
         g_tracks[tidx].above_excursions++;
         if(g_tracks[tidx].first_outside_side == 0)
            g_tracks[tidx].first_outside_side = +1;
      }
      else if(location == ORG_LOC_BELOW)
      {
         g_tracks[tidx].below_excursions++;
         if(g_tracks[tidx].first_outside_side == 0)
            g_tracks[tidx].first_outside_side = -1;
      }
   }

   if(location == ORG_LOC_IN_ZONE)
   {
      g_tracks[tidx].outside_run_bars = 0;
   }
   else if(location == previous &&
           previous != ORG_LOC_NOT_AVAILABLE &&
           (continuous || !InpRequireChartContinuity))
   {
      g_tracks[tidx].outside_run_bars++;
   }
   else
   {
      g_tracks[tidx].outside_run_bars = 1;
   }

   g_tracks[tidx].previous_location =
      location;

   g_tracks[tidx].last_eligible_bar_open =
      bar_open;

   LocationBuffer[index] =
      (double)location;

   GrammarEventBuffer[index] =
      (double)event;

   OutsideRunBuffer[index] =
      (double)g_tracks[tidx].outside_run_bars;

   FirstOutsideSideBuffer[index] =
      (double)g_tracks[tidx].first_outside_side;

   AboveExcursionCountBuffer[index] =
      (double)g_tracks[tidx].above_excursions;

   BelowExcursionCountBuffer[index] =
      (double)g_tracks[tidx].below_excursions;

   FailedAboveCountBuffer[index] =
      (double)g_tracks[tidx].failed_above;

   FailedBelowCountBuffer[index] =
      (double)g_tracks[tidx].failed_below;
}

//+------------------------------------------------------------------+
void ClearAllBuffers(const int rates_total)
{
   for(int i = 0; i < rates_total; ++i)
   {
      RangeHighBuffer[i]               = EMPTY_VALUE;
      RangeLowBuffer[i]                = EMPTY_VALUE;
      RangeMidBuffer[i]                = EMPTY_VALUE;
      RangeWidthBuffer[i]              = EMPTY_VALUE;
      LifecycleBuffer[i]               = EMPTY_VALUE;
      RangeOpenBuffer[i]               = 0.0;
      RangeClosedBuffer[i]             = 0.0;
      AreaActiveBuffer[i]              = 0.0;
      InteractionEligibleBuffer[i]     = 0.0;
      LocationBuffer[i]                = EMPTY_VALUE;
      GrammarEventBuffer[i]            = EMPTY_VALUE;
      OutsideRunBuffer[i]              = EMPTY_VALUE;
      FirstOutsideSideBuffer[i]        = EMPTY_VALUE;
      AboveExcursionCountBuffer[i]     = EMPTY_VALUE;
      BelowExcursionCountBuffer[i]     = EMPTY_VALUE;
      FailedAboveCountBuffer[i]        = EMPTY_VALUE;
      FailedBelowCountBuffer[i]        = EMPTY_VALUE;
   }
}

//+------------------------------------------------------------------+
void BuildInteractionHistory(const int rates_total,
                             const datetime &time[],
                             const double &close[])
{
   ArrayResize(g_tracks, 0);
   g_lastProcessedChartBar = 0;

   ClearAllBuffers(rates_total);

   // Arrays are series. Walk oldest -> newest. Index 0 is forming and is
   // never admitted to the interaction grammar.
   for(int i = rates_total - 1;
       i >= 1 && !IsStopped();
       --i)
   {
      ProcessInteractionBar(
         i, time[i], close[i]);

      if(g_lastProcessedChartBar == 0 ||
         time[i] > g_lastProcessedChartBar)
         g_lastProcessedChartBar = time[i];
   }

   // Current bar receives lifecycle/geometry metadata only.
   PublishBaseFields(0, time[0]);
}

//+------------------------------------------------------------------+
void ProcessNewChartBars(const int rates_total,
                         const datetime &time[],
                         const double &close[])
{
   if(g_lastProcessedChartBar == 0)
   {
      BuildInteractionHistory(
         rates_total, time, close);
      return;
   }

   int oldest_new_index = 0;

   // Find every completed chart bar newer than the last processed one.
   for(int i = 1; i < rates_total; ++i)
   {
      if(time[i] > g_lastProcessedChartBar)
         oldest_new_index = i;
      else
         break;
   }

   for(int i = oldest_new_index; i >= 1; --i)
   {
      if(time[i] <= g_lastProcessedChartBar)
         continue;

      ProcessInteractionBar(
         i, time[i], close[i]);

      g_lastProcessedChartBar = time[i];
   }

   // Keep the forming bar free of transition claims.
   PublishBaseFields(0, time[0]);
}

//+------------------------------------------------------------------+
void RefreshRecentBaseMetadata(const int rates_total,
                               const datetime &time[])
{
   // Range geometry changes only while collecting and freezes once. We update
   // a bounded recent window so Data Window metadata tracks those phase changes
   // without rescanning deep history each source minute.
   const int period_seconds =
      MathMax(PeriodSeconds(_Period), 60);

   const int session_seconds =
      (InpAreaEndHour * 60 + InpAreaEndMinute -
       (InpStartHour * 60 + InpStartMinute)) * 60;

   const int limit =
      MathMin(
         rates_total,
         MathMax(
            32,
            session_seconds /
            period_seconds + 16));

   for(int i = 0; i < limit; ++i)
   {
      // Preserve completed interaction fields on eligible bars.
      const double eligible =
         InteractionEligibleBuffer[i];
      const double location =
         LocationBuffer[i];
      const double event =
         GrammarEventBuffer[i];
      const double outsideRun =
         OutsideRunBuffer[i];
      const double firstSide =
         FirstOutsideSideBuffer[i];
      const double aboveCount =
         AboveExcursionCountBuffer[i];
      const double belowCount =
         BelowExcursionCountBuffer[i];
      const double failedAbove =
         FailedAboveCountBuffer[i];
      const double failedBelow =
         FailedBelowCountBuffer[i];

      PublishBaseFields(i, time[i]);

      if(i > 0 && eligible == 1.0)
      {
         InteractionEligibleBuffer[i] = eligible;
         LocationBuffer[i]            = location;
         GrammarEventBuffer[i]        = event;
         OutsideRunBuffer[i]          = outsideRun;
         FirstOutsideSideBuffer[i]    = firstSide;
         AboveExcursionCountBuffer[i] = aboveCount;
         BelowExcursionCountBuffer[i] = belowCount;
         FailedAboveCountBuffer[i]    = failedAbove;
         FailedBelowCountBuffer[i]    = failedBelow;
      }
   }
}

//+------------------------------------------------------------------+
void CommonObject(const string name)
{
   ObjectSetInteger(
      0, name, OBJPROP_SELECTABLE, false);

   ObjectSetInteger(
      0, name, OBJPROP_SELECTED, false);

   ObjectSetInteger(
      0, name, OBJPROP_HIDDEN, true);
}

//+------------------------------------------------------------------+
void UpsertRectangle(const string name,
                     const datetime t1,
                     const double p1,
                     const datetime t2,
                     const double p2,
                     const color c,
                     const int alpha)
{
   if(ObjectFind(0, name) < 0)
      ObjectCreate(
         0, name, OBJ_RECTANGLE,
         0, t1, p1, t2, p2);

   ObjectMove(0, name, 0, t1, p1);
   ObjectMove(0, name, 1, t2, p2);

   ObjectSetInteger(
      0, name, OBJPROP_COLOR,
      (color)ColorToARGB(
         c, (uchar)alpha));

   ObjectSetInteger(
      0, name, OBJPROP_FILL, true);

   ObjectSetInteger(
      0, name, OBJPROP_BACK, true);

   CommonObject(name);
}

//+------------------------------------------------------------------+
void UpsertLine(const string name,
                const datetime t1,
                const double p,
                const datetime t2,
                const color c,
                const ENUM_LINE_STYLE style)
{
   if(ObjectFind(0, name) < 0)
      ObjectCreate(
         0, name, OBJ_TREND,
         0, t1, p, t2, p);

   ObjectMove(0, name, 0, t1, p);
   ObjectMove(0, name, 1, t2, p);

   ObjectSetInteger(
      0, name, OBJPROP_RAY_LEFT, false);

   ObjectSetInteger(
      0, name, OBJPROP_RAY_RIGHT, false);

   ObjectSetInteger(
      0, name, OBJPROP_COLOR, c);

   ObjectSetInteger(
      0, name, OBJPROP_STYLE, style);

   ObjectSetInteger(
      0, name, OBJPROP_WIDTH,
      InpRailWidth);

   CommonObject(name);
}

//+------------------------------------------------------------------+
void UpsertLabel(const string name,
                 const datetime t,
                 const double p,
                 const string text,
                 const color c)
{
   if(ObjectFind(0, name) < 0)
      ObjectCreate(
         0, name, OBJ_TEXT,
         0, t, p);

   ObjectMove(0, name, 0, t, p);

   ObjectSetString(
      0, name, OBJPROP_TEXT, text);

   ObjectSetInteger(
      0, name, OBJPROP_COLOR, c);

   ObjectSetInteger(
      0, name, OBJPROP_FONTSIZE, 8);

   ObjectSetInteger(
      0, name, OBJPROP_ANCHOR,
      ANCHOR_LEFT_LOWER);

   CommonObject(name);
}

//+------------------------------------------------------------------+
void DeleteSessionObjects(const datetime day)
{
   const string base =
      g_prefix + DayKey(day) + "_";

   ObjectDelete(0, base + "RANGE");
   ObjectDelete(0, base + "AREA");
   ObjectDelete(0, base + "HIGH");
   ObjectDelete(0, base + "LOW");
   ObjectDelete(0, base + "MID");
   ObjectDelete(0, base + "LABEL");
}

//+------------------------------------------------------------------+
int FindRendered(const datetime day)
{
   for(int i = ArraySize(g_rendered) - 1;
       i >= 0;
       --i)
   {
      if(g_rendered[i].day_start == day)
         return i;
   }

   return -1;
}

//+------------------------------------------------------------------+
bool SessionExists(const datetime day)
{
   return FindSession(day) >= 0;
}

//+------------------------------------------------------------------+
bool RenderChanged(const ORG_SESSION &s,
                   const int ridx)
{
   if(ridx < 0)
      return true;

   if(g_rendered[ridx].state != s.state ||
      g_rendered[ridx].has_geometry !=
         s.has_geometry ||
      g_rendered[ridx].evaluable !=
         s.evaluable ||
      g_rendered[ridx].closed_m1_bars !=
         s.closed_m1_bars)
      return true;

   if(s.has_geometry)
   {
      if(MathAbs(
            g_rendered[ridx].high -
            s.high) > _Point * 0.1 ||
         MathAbs(
            g_rendered[ridx].low -
            s.low) > _Point * 0.1)
         return true;
   }

   return false;
}

//+------------------------------------------------------------------+
void CommitRenderReceipt(const ORG_SESSION &s,
                         const int ridx)
{
   int slot = ridx;

   if(slot < 0)
   {
      slot = ArraySize(g_rendered);
      ArrayResize(g_rendered, slot + 1);
   }

   g_rendered[slot].day_start =
      s.day_start;

   g_rendered[slot].high =
      s.high;

   g_rendered[slot].low =
      s.low;

   g_rendered[slot].closed_m1_bars =
      s.closed_m1_bars;

   g_rendered[slot].state =
      s.state;

   g_rendered[slot].has_geometry =
      s.has_geometry;

   g_rendered[slot].evaluable =
      s.evaluable;
}

//+------------------------------------------------------------------+
void PurgeAgedRenderReceipts()
{
   ORG_RENDER_RECEIPT keep[];
   ArrayResize(keep, 0);

   for(int i = 0;
       i < ArraySize(g_rendered);
       ++i)
   {
      if(SessionExists(
            g_rendered[i].day_start))
      {
         const int n =
            ArraySize(keep);

         ArrayResize(keep, n + 1);
         keep[n] = g_rendered[i];
      }
      else
      {
         DeleteSessionObjects(
            g_rendered[i].day_start);
      }
   }

   ArrayResize(
      g_rendered,
      ArraySize(keep));

   for(int i = 0;
       i < ArraySize(keep);
       ++i)
      g_rendered[i] = keep[i];
}

//+------------------------------------------------------------------+
// Original visual grammar:
// [range_start, range_end] = red capture area
// [range_end, area_end]    = violet continuation area + H/L rails
//
// Interaction grammar remains machine/Data-Window only in V1.02.
//+------------------------------------------------------------------+
void RenderSession(const ORG_SESSION &s)
{
   if(!s.has_geometry)
      return;

   const string base =
      g_prefix +
      DayKey(s.day_start) +
      "_";

   if(InpShowRangeArea)
   {
      UpsertRectangle(
         base + "RANGE",
         s.range_start, s.high,
         s.range_end,   s.low,
         InpRangeColor,
         InpRangeAlpha);
   }
   else
      ObjectDelete(
         0, base + "RANGE");

   const bool frozen =
      s.evaluable &&
      (s.state == ORG_FROZEN ||
       s.state == ORG_COMPLETE);

   if(frozen)
   {
      if(InpShowPostRangeArea)
      {
         UpsertRectangle(
            base + "AREA",
            s.range_end, s.high,
            s.area_end,  s.low,
            InpExtensionColor,
            InpExtensionAlpha);
      }
      else
         ObjectDelete(
            0, base + "AREA");

      UpsertLine(
         base + "HIGH",
         s.range_end, s.high,
         s.area_end,
         InpExtensionColor,
         InpRailStyle);

      UpsertLine(
         base + "LOW",
         s.range_end, s.low,
         s.area_end,
         InpExtensionColor,
         InpRailStyle);

      if(InpShowMidline)
      {
         const double mid =
            0.5 * (s.high + s.low);

         UpsertLine(
            base + "MID",
            s.range_end, mid,
            s.area_end,
            InpMidColor,
            STYLE_DOT);
      }
      else
         ObjectDelete(
            0, base + "MID");
   }
   else
   {
      ObjectDelete(0, base + "AREA");
      ObjectDelete(0, base + "HIGH");
      ObjectDelete(0, base + "LOW");
      ObjectDelete(0, base + "MID");
   }

   if(InpShowLabels)
   {
      const color labelColor =
         s.evaluable
         ? ((s.state == ORG_COLLECTING)
            ? InpRangeColor
            : InpExtensionColor)
         : clrTomato;

      string label =
         "OR " +
         IntegerToString(
            InpRangeMinutes) +
         "m " +
         ZoneChartText(s);

      if(s.state == ORG_COLLECTING)
      {
         label +=
            " M1=" +
            IntegerToString(
               s.closed_m1_bars) +
            "/" +
            IntegerToString(
               s.expected_m1_bars);
      }

      UpsertLabel(
         base + "LABEL",
         s.range_end,
         s.high,
         label,
         labelColor);
   }
   else
      ObjectDelete(
         0, base + "LABEL");
}

//+------------------------------------------------------------------+
void RenderChangedSessions()
{
   PurgeAgedRenderReceipts();

   bool changed = false;

   for(int i = 0;
       i < ArraySize(g_sessions);
       ++i)
   {
      if(!g_sessions[i].has_geometry)
         continue;

      const int ridx =
         FindRendered(
            g_sessions[i].day_start);

      if(!RenderChanged(
            g_sessions[i], ridx))
         continue;

      RenderSession(g_sessions[i]);

      CommitRenderReceipt(
         g_sessions[i], ridx);

      changed = true;
   }

   if(changed)
      ChartRedraw(0);
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
   if(rates_total < 10)
      return 0;

   ArraySetAsSeries(time, true);
   ArraySetAsSeries(close, true);

   const datetime now =
      TimeCurrent();

   bool source_changed = false;
   bool full_rebuild = false;

   if(prev_calculated == 0 ||
      g_lastClosedM1 == 0)
   {
      source_changed =
         BuildInitialHistory(now);

      full_rebuild = true;
   }
   else
   {
      const datetime latestClosedM1 =
         iTime(_Symbol, PERIOD_M1, 1);

      if(latestClosedM1 != g_lastClosedM1)
      {
         source_changed =
            UpdateNewClosedM1(now);
      }
      else
      {
         UpdateStates(now);
      }
   }

   // Range lifecycle can cross FROZEN/COMPLETE on a clock boundary even
   // without an interaction-timeframe bar closing at that instant.
   UpdateStates(now);

   if(full_rebuild)
   {
      BuildInteractionHistory(
         rates_total,
         time,
         close);
   }
   else
   {
      ProcessNewChartBars(
         rates_total,
         time,
         close);

      if(source_changed)
      {
         RefreshRecentBaseMetadata(
            rates_total,
            time);
      }
      else
      {
         // Keep the current forming bar's lifecycle metadata current.
         PublishBaseFields(
            0, time[0]);
      }
   }

   RenderChangedSessions();

   return rates_total;
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   ObjectsDeleteAll(
      0, g_prefix);

   ChartRedraw(0);
}
//+------------------------------------------------------------------+
