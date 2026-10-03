//+------------------------------------------------------------------+
//|                              KittSharpPullbackHL_LH_v1.mq5       |
//| Event-driven higher-low / lower-high continuation detector      |
//+------------------------------------------------------------------+
#property copyright "Kitt adaptation 2026"
#property version   "1.00"
#property strict
#property indicator_chart_window
#property indicator_buffers 8
#property indicator_plots   8

#property indicator_label1  "Confirmed Higher Low"
#property indicator_type1   DRAW_ARROW
#property indicator_color1  clrDeepSkyBlue
#property indicator_width1  2
#property indicator_label2  "Confirmed Lower High"
#property indicator_type2   DRAW_ARROW
#property indicator_color2  clrTomato
#property indicator_width2  2
#property indicator_label3  "Bull HL Confirmation Bar"
#property indicator_type3   DRAW_ARROW
#property indicator_color3  clrYellow
#property indicator_width3  1
#property indicator_label4  "Bear LH Confirmation Bar"
#property indicator_type4   DRAW_ARROW
#property indicator_color4  clrYellow
#property indicator_width4  1
#property indicator_label5  "Bull Continuation Validated"
#property indicator_type5   DRAW_ARROW
#property indicator_color5  clrLimeGreen
#property indicator_width5  1
#property indicator_label6  "Bear Continuation Validated"
#property indicator_type6   DRAW_ARROW
#property indicator_color6  clrMagenta
#property indicator_width6  1
#property indicator_label7  "Developing Higher Low"
#property indicator_type7   DRAW_ARROW
#property indicator_color7  clrAqua
#property indicator_width7  1
#property indicator_label8  "Developing Lower High"
#property indicator_type8   DRAW_ARROW
#property indicator_color8  clrOrange
#property indicator_width8  1

input group "Sharp Impulse"
input int    InpATRPeriod             = 14;
input double InpMinimumImpulseATR     = 1.50;
input double InpMinimumEfficiency     = 0.55;
input double InpPullbackActivationATR = 0.30;

input group "Pullback Qualification"
input double InpMinimumRetracement    = 0.146;
input double InpMaximumRetracement    = 0.786;
input double InpConfirmationATR       = 0.35;
input double InpStructureBufferATR    = 0.02;

input group "Display"
input string InpInstanceTag           = "Main";
input bool   InpShowCandidates        = true;
input bool   InpShowConfirmationDots  = true;
input bool   InpShowValidationDots    = true;
input bool   InpShowPatternLabels     = true;
input bool   InpShowStatus            = true;
input int    InpMaximumPatterns       = 80;
input int    InpLineWidth             = 2;
input color  InpBullColor             = clrDeepSkyBlue;
input color  InpBearColor             = clrTomato;

double HigherLowBuffer[];
double LowerHighBuffer[];
double BullConfirmationBuffer[];
double BearConfirmationBuffer[];
double BullValidationBuffer[];
double BearValidationBuffer[];
double CandidateHLBuffer[];
double CandidateLHBuffer[];
double g_atrSlice[];

enum ENUM_PATTERN_STATE
{
   STATE_SEARCH = 0,
   STATE_BULL_IMPULSE,
   STATE_BEAR_IMPULSE,
   STATE_BULL_PULLBACK,
   STATE_BEAR_PULLBACK,
   STATE_BULL_CONTINUATION,
   STATE_BEAR_CONTINUATION
};

ENUM_PATTERN_STATE g_state = STATE_SEARCH;
int      g_atrHandle      = INVALID_HANDLE;
datetime g_lastClosedTime = 0;
double   g_lastATR        = 0.0;

// Simultaneous event origins while searching.
double   g_bullOriginPrice = 0.0;
double   g_bearOriginPrice = 0.0;
datetime g_bullOriginTime  = 0;
datetime g_bearOriginTime  = 0;
int      g_bullOriginIndex = -1;
int      g_bearOriginIndex = -1;
double   g_bullPath        = 0.0;
double   g_bearPath        = 0.0;
double   g_previousClose   = 0.0;

// Active impulse and pullback.
double   g_originPrice      = 0.0;
double   g_peakPrice        = 0.0;
datetime g_originTime       = 0;
datetime g_peakTime         = 0;
int      g_originIndex      = -1;
int      g_peakIndex        = -1;
double   g_impulsePath      = 0.0;
double   g_impulseEfficiency= 0.0;

double   g_candidatePrice   = 0.0;
datetime g_candidateTime    = 0;
int      g_candidateIndex   = -1;
double   g_retracement      = 0.0;

double   g_confirmedPrice   = 0.0;
datetime g_confirmedTime    = 0;
int      g_confirmedIndex   = -1;
double   g_continuationPath = 0.0;
double   g_continuationPrevClose = 0.0;
int      g_activePatternSerial = -1;

int    g_patternSerial = 0;
string g_prefix = "KittSharpPB_";

//+------------------------------------------------------------------+
//| Small helpers                                                    |
//+------------------------------------------------------------------+
double SafeEfficiency(const double displacement, const double path)
{
   if(displacement <= 0.0)
      return(0.0);
   return(displacement / MathMax(displacement, path));
}

string ObjectName(const int serial, const string suffix)
{
   return(g_prefix + IntegerToString(serial) + "_" + suffix);
}

string StateText()
{
   switch(g_state)
   {
      case STATE_SEARCH:            return("SEARCHING");
      case STATE_BULL_IMPULSE:      return("BULL IMPULSE");
      case STATE_BEAR_IMPULSE:      return("BEAR IMPULSE");
      case STATE_BULL_PULLBACK:     return("BULL PULLBACK");
      case STATE_BEAR_PULLBACK:     return("BEAR PULLBACK");
      case STATE_BULL_CONTINUATION: return("BULL HL CONFIRMED");
      case STATE_BEAR_CONTINUATION: return("BEAR LH CONFIRMED");
   }
   return("UNKNOWN");
}

void ClearCandidateMarker()
{
   if(g_candidateIndex >= 0)
   {
      CandidateHLBuffer[g_candidateIndex] = EMPTY_VALUE;
      CandidateLHBuffer[g_candidateIndex] = EMPTY_VALUE;
   }
   g_candidatePrice = 0.0;
   g_candidateTime  = 0;
   g_candidateIndex = -1;
   g_retracement    = 0.0;
}

void ResetSearchAt(
   const int bar,
   const datetime &time[],
   const double &high[],
   const double &low[],
   const double &close[]
)
{
   ClearCandidateMarker();
   g_state = STATE_SEARCH;

   g_bullOriginPrice = low[bar];
   g_bullOriginTime  = time[bar];
   g_bullOriginIndex = bar;
   g_bearOriginPrice = high[bar];
   g_bearOriginTime  = time[bar];
   g_bearOriginIndex = bar;
   g_bullPath = MathAbs(close[bar] - low[bar]);
   g_bearPath = MathAbs(high[bar] - close[bar]);
   g_previousClose = close[bar];

   g_originPrice = 0.0;
   g_peakPrice   = 0.0;
   g_originTime  = 0;
   g_peakTime    = 0;
   g_originIndex = -1;
   g_peakIndex   = -1;
   g_impulsePath = 0.0;
   g_impulseEfficiency = 0.0;
   g_confirmedPrice = 0.0;
   g_confirmedTime  = 0;
   g_confirmedIndex = -1;
   g_continuationPath = 0.0;
   g_continuationPrevClose = close[bar];
   g_activePatternSerial = -1;
}

void ResetAllState()
{
   g_state = STATE_SEARCH;
   g_lastClosedTime = 0;
   g_lastATR = 0.0;
   g_patternSerial = 0;
   g_candidateIndex = -1;
   g_activePatternSerial = -1;
   g_bullOriginIndex = -1;
   g_bearOriginIndex = -1;
   g_originIndex = -1;
   g_peakIndex = -1;
   g_confirmedIndex = -1;
}

//+------------------------------------------------------------------+
//| Object drawing                                                   |
//+------------------------------------------------------------------+
void EnsureTrendLine(
   const string name,
   const datetime t1,
   const double p1,
   const datetime t2,
   const double p2,
   const color lineColor
)
{
   if(ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_TREND, 0, t1, p1, t2, p2);
   else
   {
      ObjectMove(0, name, 0, t1, p1);
      ObjectMove(0, name, 1, t2, p2);
   }

   ObjectSetInteger(0, name, OBJPROP_RAY_LEFT, false);
   ObjectSetInteger(0, name, OBJPROP_RAY_RIGHT, false);
   ObjectSetInteger(0, name, OBJPROP_COLOR, lineColor);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, MathMax(InpLineWidth, 1));
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
}

void DeletePattern(const int serial)
{
   ObjectDelete(0, ObjectName(serial, "IMPULSE"));
   ObjectDelete(0, ObjectName(serial, "PULLBACK"));
   ObjectDelete(0, ObjectName(serial, "CONTINUATION"));
   ObjectDelete(0, ObjectName(serial, "LABEL"));
}

void CreatePatternObjects(
   const int direction,
   const datetime confirmationTime,
   const double confirmationPrice
)
{
   const int serial = g_patternSerial++;
   g_activePatternSerial = serial;

   const color trendColor = direction > 0 ? InpBullColor : InpBearColor;
   const color pullbackColor = direction > 0 ? InpBearColor : InpBullColor;

   EnsureTrendLine(
      ObjectName(serial, "IMPULSE"),
      g_originTime, g_originPrice,
      g_peakTime, g_peakPrice,
      trendColor
   );
   EnsureTrendLine(
      ObjectName(serial, "PULLBACK"),
      g_peakTime, g_peakPrice,
      g_confirmedTime, g_confirmedPrice,
      pullbackColor
   );
   EnsureTrendLine(
      ObjectName(serial, "CONTINUATION"),
      g_confirmedTime, g_confirmedPrice,
      confirmationTime, confirmationPrice,
      trendColor
   );

   if(InpShowPatternLabels)
   {
      const string name = ObjectName(serial, "LABEL");
      ObjectCreate(0, name, OBJ_TEXT, 0, g_confirmedTime, g_confirmedPrice);
      ObjectSetString(
         0, name, OBJPROP_TEXT,
         StringFormat(
            "%s %.1f%% | E %.2f",
            direction > 0 ? "HL" : "LH",
            g_retracement * 100.0,
            g_impulseEfficiency
         )
      );
      ObjectSetInteger(0, name, OBJPROP_COLOR, trendColor);
      ObjectSetInteger(0, name, OBJPROP_FONTSIZE, 8);
      ObjectSetInteger(0, name, OBJPROP_ANCHOR,
                       direction > 0 ? ANCHOR_LEFT_UPPER : ANCHOR_LEFT_LOWER);
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
   }

   const int expired = serial - MathMax(InpMaximumPatterns, 1);
   if(expired >= 0)
      DeletePattern(expired);
}

void UpdateContinuationLine(
   const datetime when,
   const double price,
   const int direction
)
{
   if(g_activePatternSerial < 0)
      return;

   EnsureTrendLine(
      ObjectName(g_activePatternSerial, "CONTINUATION"),
      g_confirmedTime, g_confirmedPrice,
      when, price,
      direction > 0 ? InpBullColor : InpBearColor
   );
}

void UpdateStatus()
{
   const string name = g_prefix + "STATUS";
   if(!InpShowStatus)
   {
      ObjectDelete(0, name);
      return;
   }

   if(ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0);

   string text = "Sharp Pullback: " + StateText();
   if(g_state == STATE_BULL_PULLBACK || g_state == STATE_BEAR_PULLBACK)
      text += StringFormat(" | R %.1f%%", g_retracement * 100.0);
   if(g_state == STATE_BULL_IMPULSE || g_state == STATE_BEAR_IMPULSE)
      text += StringFormat(" | E %.2f", g_impulseEfficiency);

   ObjectSetString(0, name, OBJPROP_TEXT, text);
   ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(0, name, OBJPROP_ANCHOR, ANCHOR_LEFT_UPPER);
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, 12);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, 18);
   ObjectSetInteger(0, name, OBJPROP_COLOR, clrSilver);
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE, 9);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
}

//+------------------------------------------------------------------+
//| ATR                                                              |
//+------------------------------------------------------------------+
bool CopyAtrRange(const int start, const int lastClosed)
{
   const int count = lastClosed - start + 1;
   if(count <= 0 || ArrayResize(g_atrSlice, count) != count)
      return(false);

   ResetLastError();
   const int copied = CopyBuffer(g_atrHandle, 0, 1, count, g_atrSlice);
   if(copied != count)
   {
      PrintFormat("ATR requested %d, copied %d, error %d",
                  count, copied, GetLastError());
      return(false);
   }
   return(true);
}

//+------------------------------------------------------------------+
//| Event-driven search                                              |
//+------------------------------------------------------------------+
void ActivateImpulse(
   const int direction,
   const int bar,
   const datetime &time[],
   const double &high[],
   const double &low[]
)
{
   if(direction > 0)
   {
      g_state       = STATE_BULL_IMPULSE;
      g_originPrice = g_bullOriginPrice;
      g_originTime  = g_bullOriginTime;
      g_originIndex = g_bullOriginIndex;
      g_peakPrice   = high[bar];
      g_peakTime    = time[bar];
      g_peakIndex   = bar;
      g_impulsePath = g_bullPath;
   }
   else
   {
      g_state       = STATE_BEAR_IMPULSE;
      g_originPrice = g_bearOriginPrice;
      g_originTime  = g_bearOriginTime;
      g_originIndex = g_bearOriginIndex;
      g_peakPrice   = low[bar];
      g_peakTime    = time[bar];
      g_peakIndex   = bar;
      g_impulsePath = g_bearPath;
   }

   g_impulseEfficiency = SafeEfficiency(
      MathAbs(g_peakPrice - g_originPrice),
      g_impulsePath
   );
}

void SearchForImpulse(
   const int bar,
   const double atr,
   const datetime &time[],
   const double &high[],
   const double &low[],
   const double &close[]
)
{
   const double step = MathAbs(close[bar] - g_previousClose);
   g_bullPath += step;
   g_bearPath += step;

   if(low[bar] <= g_bullOriginPrice)
   {
      g_bullOriginPrice = low[bar];
      g_bullOriginTime  = time[bar];
      g_bullOriginIndex = bar;
      g_bullPath = MathAbs(close[bar] - low[bar]);
   }

   if(high[bar] >= g_bearOriginPrice)
   {
      g_bearOriginPrice = high[bar];
      g_bearOriginTime  = time[bar];
      g_bearOriginIndex = bar;
      g_bearPath = MathAbs(high[bar] - close[bar]);
   }

   const double bullMove = high[bar] - g_bullOriginPrice;
   const double bearMove = g_bearOriginPrice - low[bar];
   const double bullEfficiency = SafeEfficiency(bullMove, g_bullPath);
   const double bearEfficiency = SafeEfficiency(bearMove, g_bearPath);
   const bool bullQualified =
      bullMove >= atr * InpMinimumImpulseATR &&
      bullEfficiency >= InpMinimumEfficiency;
   const bool bearQualified =
      bearMove >= atr * InpMinimumImpulseATR &&
      bearEfficiency >= InpMinimumEfficiency;

   if(bullQualified || bearQualified)
   {
      const double bullScore = bullMove / atr * bullEfficiency;
      const double bearScore = bearMove / atr * bearEfficiency;
      ActivateImpulse(
         bullQualified && (!bearQualified || bullScore >= bearScore) ? 1 : -1,
         bar, time, high, low
      );
   }

   g_previousClose = close[bar];
}

void StartPullback(
   const int direction,
   const int bar,
   const datetime &time[],
   const double &high[],
   const double &low[]
)
{
   ClearCandidateMarker();
   g_state = direction > 0 ? STATE_BULL_PULLBACK : STATE_BEAR_PULLBACK;
   g_candidatePrice = direction > 0 ? low[bar] : high[bar];
   g_candidateTime  = time[bar];
   g_candidateIndex = bar;

   if(InpShowCandidates)
   {
      if(direction > 0)
         CandidateHLBuffer[bar] = g_candidatePrice;
      else
         CandidateLHBuffer[bar] = g_candidatePrice;
   }
}

void TrackImpulse(
   const int direction,
   const int bar,
   const double atr,
   const datetime &time[],
   const double &high[],
   const double &low[],
   const double &close[]
)
{
   g_impulsePath += MathAbs(close[bar] - g_previousClose);
   g_previousClose = close[bar];

   if(direction > 0)
   {
      if(high[bar] >= g_peakPrice)
      {
         g_peakPrice = high[bar];
         g_peakTime  = time[bar];
         g_peakIndex = bar;
      }

      if(close[bar] <= g_originPrice)
      {
         ResetSearchAt(bar, time, high, low, close);
         return;
      }

      if(close[bar] <= g_peakPrice - atr * InpPullbackActivationATR)
      {
         StartPullback(1, bar, time, high, low);
         // The activation candle may itself sweep and reclaim the low.
         // Evaluate it immediately rather than imposing a hidden bar delay.
         TrackPullback(1, bar, atr, time, high, low, close);
      }
   }
   else
   {
      if(low[bar] <= g_peakPrice)
      {
         g_peakPrice = low[bar];
         g_peakTime  = time[bar];
         g_peakIndex = bar;
      }

      if(close[bar] >= g_originPrice)
      {
         ResetSearchAt(bar, time, high, low, close);
         return;
      }

      if(close[bar] >= g_peakPrice + atr * InpPullbackActivationATR)
      {
         StartPullback(-1, bar, time, high, low);
         TrackPullback(-1, bar, atr, time, high, low, close);
      }
   }

   g_impulseEfficiency = SafeEfficiency(
      MathAbs(g_peakPrice - g_originPrice),
      g_impulsePath
   );
}

void UpdateCandidate(
   const int direction,
   const int bar,
   const datetime &time[],
   const double candidatePrice
)
{
   if(g_candidateIndex >= 0)
   {
      CandidateHLBuffer[g_candidateIndex] = EMPTY_VALUE;
      CandidateLHBuffer[g_candidateIndex] = EMPTY_VALUE;
   }

   g_candidatePrice = candidatePrice;
   g_candidateTime  = time[bar];
   g_candidateIndex = bar;

   if(InpShowCandidates)
   {
      if(direction > 0)
         CandidateHLBuffer[bar] = candidatePrice;
      else
         CandidateLHBuffer[bar] = candidatePrice;
   }
}

void ConfirmPullback(
   const int direction,
   const int bar,
   const datetime &time[],
   const double &high[],
   const double &low[],
   const double &close[]
)
{
   const double confirmedRetracement = g_retracement;
   g_confirmedPrice = g_candidatePrice;
   g_confirmedTime  = g_candidateTime;
   g_confirmedIndex = g_candidateIndex;

   if(direction > 0)
      HigherLowBuffer[g_confirmedIndex] = g_confirmedPrice;
   else
      LowerHighBuffer[g_confirmedIndex] = g_confirmedPrice;

   // The large arrow is back-plotted at the actual HL/LH. This small dot
   // records the candle on which that pivot first became knowable.
   if(InpShowConfirmationDots)
   {
      if(direction > 0)
         BullConfirmationBuffer[bar] = low[bar];
      else
         BearConfirmationBuffer[bar] = high[bar];
   }

   ClearCandidateMarker();
   g_retracement = confirmedRetracement;
   CreatePatternObjects(direction, time[bar], close[bar]);

   g_state = direction > 0
      ? STATE_BULL_CONTINUATION
      : STATE_BEAR_CONTINUATION;
   g_continuationPath = MathAbs(close[bar] - g_confirmedPrice);
   g_continuationPrevClose = close[bar];
}

void TrackPullback(
   const int direction,
   const int bar,
   const double atr,
   const datetime &time[],
   const double &high[],
   const double &low[],
   const double &close[]
)
{
   const double impulseRange = MathAbs(g_peakPrice - g_originPrice);
   if(impulseRange <= 0.0)
   {
      ResetSearchAt(bar, time, high, low, close);
      return;
   }

   if(direction > 0 && high[bar] > g_peakPrice)
   {
      ClearCandidateMarker();
      g_state = STATE_BULL_IMPULSE;
      g_peakPrice = high[bar];
      g_peakTime  = time[bar];
      g_peakIndex = bar;
      g_previousClose = close[bar];
      return;
   }
   if(direction < 0 && low[bar] < g_peakPrice)
   {
      ClearCandidateMarker();
      g_state = STATE_BEAR_IMPULSE;
      g_peakPrice = low[bar];
      g_peakTime  = time[bar];
      g_peakIndex = bar;
      g_previousClose = close[bar];
      return;
   }

   if(direction > 0 && low[bar] < g_candidatePrice)
      UpdateCandidate(1, bar, time, low[bar]);
   if(direction < 0 && high[bar] > g_candidatePrice)
      UpdateCandidate(-1, bar, time, high[bar]);

   g_retracement = direction > 0
      ? (g_peakPrice - g_candidatePrice) / impulseRange
      : (g_candidatePrice - g_peakPrice) / impulseRange;

   const bool structureHeld = direction > 0
      ? g_candidatePrice > g_originPrice + atr * InpStructureBufferATR
      : g_candidatePrice < g_originPrice - atr * InpStructureBufferATR;

   if(!structureHeld || g_retracement > InpMaximumRetracement)
   {
      ResetSearchAt(bar, time, high, low, close);
      return;
   }

   const bool depthQualified = g_retracement >= InpMinimumRetracement;
   const bool reversalConfirmed = direction > 0
      ? close[bar] >= g_candidatePrice + atr * InpConfirmationATR
      : close[bar] <= g_candidatePrice - atr * InpConfirmationATR;

   if(depthQualified && reversalConfirmed)
      ConfirmPullback(direction, bar, time, high, low, close);
}

void TrackContinuation(
   const int direction,
   const int bar,
   const double atr,
   const datetime &time[],
   const double &high[],
   const double &low[],
   const double &close[]
)
{
   g_continuationPath += MathAbs(close[bar] - g_continuationPrevClose);
   g_continuationPrevClose = close[bar];

   UpdateContinuationLine(
      time[bar],
      direction > 0 ? high[bar] : low[bar],
      direction
   );

   const bool invalidated = direction > 0
      ? close[bar] <= g_confirmedPrice
      : close[bar] >= g_confirmedPrice;

   if(invalidated)
   {
      ResetSearchAt(bar, time, high, low, close);
      return;
   }

   const bool validated = direction > 0
      ? high[bar] >= g_peakPrice
      : low[bar] <= g_peakPrice;

   if(!validated)
      return;

   if(InpShowValidationDots)
   {
      if(direction > 0)
         BullValidationBuffer[bar] = high[bar];
      else
         BearValidationBuffer[bar] = low[bar];
   }

   const double newDisplacement = MathAbs(
      (direction > 0 ? high[bar] : low[bar]) - g_confirmedPrice
   );
   const double newEfficiency = SafeEfficiency(
      newDisplacement,
      g_continuationPath
   );

   // Chain directly into another impulse when the continuation itself
   // is already sharp enough. Otherwise begin a fresh event search.
   if(newDisplacement >= atr * InpMinimumImpulseATR &&
      newEfficiency >= InpMinimumEfficiency)
   {
      g_originPrice = g_confirmedPrice;
      g_originTime  = g_confirmedTime;
      g_originIndex = g_confirmedIndex;
      g_peakPrice   = direction > 0 ? high[bar] : low[bar];
      g_peakTime    = time[bar];
      g_peakIndex   = bar;
      g_impulsePath = g_continuationPath;
      g_impulseEfficiency = newEfficiency;
      g_previousClose = close[bar];
      g_state = direction > 0 ? STATE_BULL_IMPULSE : STATE_BEAR_IMPULSE;
      g_activePatternSerial = -1;
   }
   else
   {
      ResetSearchAt(bar, time, high, low, close);
   }
}

void ProcessClosedBar(
   const int bar,
   const double atr,
   const datetime &time[],
   const double &high[],
   const double &low[],
   const double &close[]
)
{
   HigherLowBuffer[bar]       = EMPTY_VALUE;
   LowerHighBuffer[bar]       = EMPTY_VALUE;
   BullConfirmationBuffer[bar]= EMPTY_VALUE;
   BearConfirmationBuffer[bar]= EMPTY_VALUE;
   BullValidationBuffer[bar]  = EMPTY_VALUE;
   BearValidationBuffer[bar]  = EMPTY_VALUE;
   CandidateHLBuffer[bar]     = EMPTY_VALUE;
   CandidateLHBuffer[bar]     = EMPTY_VALUE;

   if(atr <= 0.0 || atr == EMPTY_VALUE)
      return;

   switch(g_state)
   {
      case STATE_SEARCH:
         SearchForImpulse(bar, atr, time, high, low, close);
         break;
      case STATE_BULL_IMPULSE:
         TrackImpulse(1, bar, atr, time, high, low, close);
         break;
      case STATE_BEAR_IMPULSE:
         TrackImpulse(-1, bar, atr, time, high, low, close);
         break;
      case STATE_BULL_PULLBACK:
         TrackPullback(1, bar, atr, time, high, low, close);
         break;
      case STATE_BEAR_PULLBACK:
         TrackPullback(-1, bar, atr, time, high, low, close);
         break;
      case STATE_BULL_CONTINUATION:
         TrackContinuation(1, bar, atr, time, high, low, close);
         break;
      case STATE_BEAR_CONTINUATION:
         TrackContinuation(-1, bar, atr, time, high, low, close);
         break;
   }

   g_lastATR = atr;
}

//+------------------------------------------------------------------+
//| History and incremental processing                               |
//+------------------------------------------------------------------+
bool RebuildHistory(
   const int lastClosed,
   const datetime &time[],
   const double &high[],
   const double &low[],
   const double &close[]
)
{
   ArrayInitialize(HigherLowBuffer,      EMPTY_VALUE);
   ArrayInitialize(LowerHighBuffer,      EMPTY_VALUE);
   ArrayInitialize(BullConfirmationBuffer, EMPTY_VALUE);
   ArrayInitialize(BearConfirmationBuffer, EMPTY_VALUE);
   ArrayInitialize(BullValidationBuffer, EMPTY_VALUE);
   ArrayInitialize(BearValidationBuffer, EMPTY_VALUE);
   ArrayInitialize(CandidateHLBuffer,    EMPTY_VALUE);
   ArrayInitialize(CandidateLHBuffer,    EMPTY_VALUE);
   ObjectsDeleteAll(0, g_prefix, -1, -1);
   ResetAllState();

   const int start = MathMax(InpATRPeriod, 1);
   if(start >= lastClosed || !CopyAtrRange(start, lastClosed))
      return(false);

   ResetSearchAt(start, time, high, low, close);

   for(int bar = start + 1; bar <= lastClosed && !IsStopped(); ++bar)
   {
      ProcessClosedBar(
         bar,
         g_atrSlice[bar - start],
         time, high, low, close
      );
   }

   g_lastClosedTime = time[lastClosed];
   UpdateStatus();
   ChartRedraw(0);
   return(true);
}

int FindTimeIndex(
   const datetime value,
   const int lastClosed,
   const datetime &time[]
)
{
   for(int bar = lastClosed; bar >= 0; --bar)
   {
      if(time[bar] == value)
         return(bar);
      if(time[bar] < value)
         break;
   }
   return(-1);
}

//+------------------------------------------------------------------+
//| Indicator lifecycle                                              |
//+------------------------------------------------------------------+
int OnInit()
{
   if(InpATRPeriod < 2 ||
      InpMinimumImpulseATR <= 0.0 ||
      InpMinimumEfficiency <= 0.0 || InpMinimumEfficiency > 1.0 ||
      InpPullbackActivationATR <= 0.0 ||
      InpMinimumRetracement < 0.0 ||
      InpMaximumRetracement <= InpMinimumRetracement ||
      InpMaximumRetracement >= 1.0 ||
      InpConfirmationATR <= 0.0 ||
      InpStructureBufferATR < 0.0 ||
      InpMaximumPatterns < 1)
   {
      return(INIT_PARAMETERS_INCORRECT);
   }

   SetIndexBuffer(0, HigherLowBuffer,       INDICATOR_DATA);
   SetIndexBuffer(1, LowerHighBuffer,       INDICATOR_DATA);
   SetIndexBuffer(2, BullConfirmationBuffer,INDICATOR_DATA);
   SetIndexBuffer(3, BearConfirmationBuffer,INDICATOR_DATA);
   SetIndexBuffer(4, BullValidationBuffer,  INDICATOR_DATA);
   SetIndexBuffer(5, BearValidationBuffer,  INDICATOR_DATA);
   SetIndexBuffer(6, CandidateHLBuffer,     INDICATOR_DATA);
   SetIndexBuffer(7, CandidateLHBuffer,     INDICATOR_DATA);

   ArraySetAsSeries(HigherLowBuffer,       false);
   ArraySetAsSeries(LowerHighBuffer,       false);
   ArraySetAsSeries(BullConfirmationBuffer,false);
   ArraySetAsSeries(BearConfirmationBuffer,false);
   ArraySetAsSeries(BullValidationBuffer,  false);
   ArraySetAsSeries(BearValidationBuffer,  false);
   ArraySetAsSeries(CandidateHLBuffer,     false);
   ArraySetAsSeries(CandidateLHBuffer,     false);
   ArraySetAsSeries(g_atrSlice,            false);

   PlotIndexSetInteger(0, PLOT_ARROW, 233);
   PlotIndexSetInteger(1, PLOT_ARROW, 234);
   PlotIndexSetInteger(2, PLOT_ARROW, 159);
   PlotIndexSetInteger(3, PLOT_ARROW, 159);
   PlotIndexSetInteger(4, PLOT_ARROW, 159);
   PlotIndexSetInteger(5, PLOT_ARROW, 159);
   PlotIndexSetInteger(6, PLOT_ARROW, 241);
   PlotIndexSetInteger(7, PLOT_ARROW, 242);

   for(int plot = 0; plot < 8; ++plot)
   {
      PlotIndexSetDouble(plot, PLOT_EMPTY_VALUE, EMPTY_VALUE);
      PlotIndexSetInteger(plot, PLOT_DRAW_BEGIN, InpATRPeriod + 1);
   }

   g_prefix = "KittSharpPB_" + InpInstanceTag + "_";
   IndicatorSetInteger(INDICATOR_DIGITS, _Digits);
   IndicatorSetString(
      INDICATOR_SHORTNAME,
      StringFormat(
         "Kitt Sharp Pullbacks (%.2f ATR, E %.2f)",
         InpMinimumImpulseATR,
         InpMinimumEfficiency
      )
   );

   g_atrHandle = iATR(_Symbol, PERIOD_CURRENT, InpATRPeriod);
   if(g_atrHandle == INVALID_HANDLE)
   {
      PrintFormat("Could not create ATR handle. Error %d", GetLastError());
      return(INIT_FAILED);
   }

   ObjectsDeleteAll(0, g_prefix, -1, -1);
   ResetAllState();
   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason)
{
   ObjectsDeleteAll(0, g_prefix, -1, -1);
   if(g_atrHandle != INVALID_HANDLE)
   {
      IndicatorRelease(g_atrHandle);
      g_atrHandle = INVALID_HANDLE;
   }
}

int OnCalculate(
   const int rates_total,
   const int prev_calculated,
   const datetime &time[],
   const double &open[],
   const double &high[],
   const double &low[],
   const double &close[],
   const long &tick_volume[],
   const long &volume[],
   const int &spread[]
)
{
   if(rates_total < InpATRPeriod + 4)
      return(0);

   ArraySetAsSeries(time,        false);
   ArraySetAsSeries(open,        false);
   ArraySetAsSeries(high,        false);
   ArraySetAsSeries(low,         false);
   ArraySetAsSeries(close,       false);
   ArraySetAsSeries(tick_volume, false);
   ArraySetAsSeries(volume,      false);
   ArraySetAsSeries(spread,      false);

   const int currentBar = rates_total - 1;
   const int lastClosed = rates_total - 2;

   HigherLowBuffer[currentBar]       = EMPTY_VALUE;
   LowerHighBuffer[currentBar]       = EMPTY_VALUE;
   BullConfirmationBuffer[currentBar]= EMPTY_VALUE;
   BearConfirmationBuffer[currentBar]= EMPTY_VALUE;
   BullValidationBuffer[currentBar]  = EMPTY_VALUE;
   BearValidationBuffer[currentBar]  = EMPTY_VALUE;
   CandidateHLBuffer[currentBar]     = EMPTY_VALUE;
   CandidateLHBuffer[currentBar]     = EMPTY_VALUE;

   const bool rebuild =
      prev_calculated == 0 ||
      prev_calculated > rates_total ||
      g_lastClosedTime == 0;

   if(rebuild)
   {
      if(!RebuildHistory(lastClosed, time, high, low, close))
         return(0);
      return(rates_total);
   }

   if(time[lastClosed] == g_lastClosedTime)
      return(rates_total);

   const int priorIndex = FindTimeIndex(g_lastClosedTime, lastClosed, time);
   if(priorIndex < 0)
   {
      if(!RebuildHistory(lastClosed, time, high, low, close))
         return(0);
      return(rates_total);
   }

   const int start = priorIndex + 1;
   if(start <= lastClosed)
   {
      if(!CopyAtrRange(start, lastClosed))
         return(prev_calculated);

      for(int bar = start; bar <= lastClosed && !IsStopped(); ++bar)
      {
         ProcessClosedBar(
            bar,
            g_atrSlice[bar - start],
            time, high, low, close
         );
      }

      g_lastClosedTime = time[lastClosed];
      UpdateStatus();
      ChartRedraw(0);
   }

   return(rates_total);
}
//+------------------------------------------------------------------+
