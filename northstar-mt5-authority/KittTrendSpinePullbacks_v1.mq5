//+------------------------------------------------------------------+
//|                              KittTrendSpinePullbacks_v1.mq5      |
//| Trend-relative HL/LH pullbacks using robust recursive spines    |
//+------------------------------------------------------------------+
#property copyright "Kitt adaptation 2026"
#property version   "1.00"
#property strict
#property indicator_chart_window
#property indicator_buffers 12
#property indicator_plots   12

#property indicator_label1  "Slow Trend Spine"
#property indicator_type1   DRAW_LINE
#property indicator_color1  clrGold
#property indicator_width1  2
#property indicator_label2  "Fast Trigger Spine"
#property indicator_type2   DRAW_LINE
#property indicator_color2  clrDodgerBlue
#property indicator_width2  1
#property indicator_label3  "Upper Pullback Band"
#property indicator_type3   DRAW_LINE
#property indicator_color3  clrDimGray
#property indicator_style3  STYLE_DOT
#property indicator_label4  "Lower Pullback Band"
#property indicator_type4   DRAW_LINE
#property indicator_color4  clrDimGray
#property indicator_style4  STYLE_DOT
#property indicator_label5  "Confirmed Higher Low"
#property indicator_type5   DRAW_ARROW
#property indicator_color5  clrDeepSkyBlue
#property indicator_width5  2
#property indicator_label6  "Confirmed Lower High"
#property indicator_type6   DRAW_ARROW
#property indicator_color6  clrTomato
#property indicator_width6  2
#property indicator_label7  "Bull Confirmation Bar"
#property indicator_type7   DRAW_ARROW
#property indicator_color7  clrYellow
#property indicator_width7  1
#property indicator_label8  "Bear Confirmation Bar"
#property indicator_type8   DRAW_ARROW
#property indicator_color8  clrYellow
#property indicator_width8  1
#property indicator_label9  "Bull Continuation Validated"
#property indicator_type9   DRAW_ARROW
#property indicator_color9  clrLimeGreen
#property indicator_width9  1
#property indicator_label10 "Bear Continuation Validated"
#property indicator_type10  DRAW_ARROW
#property indicator_color10 clrMagenta
#property indicator_width10 1
#property indicator_label11 "Developing Higher Low"
#property indicator_type11  DRAW_ARROW
#property indicator_color11 clrAqua
#property indicator_width11 1
#property indicator_label12 "Developing Lower High"
#property indicator_type12  DRAW_ARROW
#property indicator_color12 clrOrange
#property indicator_width12 1

input group "Robust Trend Spine"
input ENUM_APPLIED_PRICE InpPriceSource       = PRICE_MEDIAN;
input int    InpATRPeriod                     = 14;
input double InpSlowAlpha                     = 0.12;
input double InpSlowBeta                      = 0.015;
input double InpFastAlpha                     = 0.35;
input double InpFastBeta                      = 0.080;
input double InpErrorClipATR                  = 1.50;
input double InpMaximumVelocityATR            = 1.00;

input group "Trend Regime"
input double InpTrendEntrySlopeATR            = 0.050;
input double InpTrendHoldSlopeATR             = 0.015;
input double InpMinimumTrendProgressATR       = 0.80;

input group "Trend-Relative Pullback"
input double InpInnerBandATR                  = 0.35;
input double InpMinimumExcursionATR           = 0.50;
input double InpMinimumPullbackATR            = 0.25;
input double InpMaximumPenetrationATR         = 0.75;
input double InpCandidateReversalATR          = 0.25;
input int    InpConfirmationScore             = 3;

input group "Display"
input string InpInstanceTag                   = "Main";
input bool   InpShowCandidates                = true;
input bool   InpShowConfirmationDots          = true;
input bool   InpShowValidationDots            = true;
input bool   InpShowStatus                    = true;

double SlowSpineBuffer[];
double FastSpineBuffer[];
double UpperBandBuffer[];
double LowerBandBuffer[];
double HigherLowBuffer[];
double LowerHighBuffer[];
double BullConfirmationBuffer[];
double BearConfirmationBuffer[];
double BullValidationBuffer[];
double BearValidationBuffer[];
double CandidateHLBuffer[];
double CandidateLHBuffer[];
double g_atrSlice[];

enum ENUM_TREND_REGIME
{
   REGIME_NEUTRAL = 0,
   REGIME_BULL    = 1,
   REGIME_BEAR    = -1
};

enum ENUM_PULLBACK_PHASE
{
   PHASE_EXPANSION = 0,
   PHASE_PULLBACK,
   PHASE_WAIT_VALIDATION
};

ENUM_TREND_REGIME  g_regime = REGIME_NEUTRAL;
ENUM_PULLBACK_PHASE g_phase = PHASE_EXPANSION;

int      g_atrHandle      = INVALID_HANDLE;
datetime g_lastClosedTime = 0;
double   g_lastATR        = 0.0;

bool   g_filterReady = false;
double g_slowLevel   = 0.0;
double g_slowVelocity= 0.0;
double g_fastLevel   = 0.0;
double g_fastVelocity= 0.0;
double g_previousSlow= 0.0;
double g_previousSpread = 0.0;

double g_bullProgress = 0.0;
double g_bearProgress = 0.0;

double   g_excursionPrice    = 0.0;
datetime g_excursionTime     = 0;
int      g_excursionIndex    = -1;
double   g_excursionDistance = 0.0;

double   g_candidatePrice = 0.0;
datetime g_candidateTime  = 0;
int      g_candidateIndex = -1;

double   g_lastBullPivot = 0.0;
double   g_lastBearPivot = 0.0;
double   g_confirmedPivot = 0.0;
datetime g_confirmedTime  = 0;
int      g_confirmedIndex = -1;
double   g_validationLevel= 0.0;

string g_prefix = "KittTrendSpine_";

//+------------------------------------------------------------------+
//| Math and prices                                                  |
//+------------------------------------------------------------------+
double Clamp(const double value, const double low, const double high)
{
   return(MathMax(low, MathMin(high, value)));
}

double AppliedPriceAt(
   const int bar,
   const double &open[],
   const double &high[],
   const double &low[],
   const double &close[]
)
{
   switch(InpPriceSource)
   {
      case PRICE_CLOSE:    return(close[bar]);
      case PRICE_OPEN:     return(open[bar]);
      case PRICE_HIGH:     return(high[bar]);
      case PRICE_LOW:      return(low[bar]);
      case PRICE_MEDIAN:   return((high[bar] + low[bar]) * 0.5);
      case PRICE_TYPICAL:  return((high[bar] + low[bar] + close[bar]) / 3.0);
      case PRICE_WEIGHTED: return((high[bar] + low[bar] + close[bar] * 2.0) / 4.0);
   }
   return(close[bar]);
}

void UpdateOneSpine(
   const double price,
   const double atr,
   const double alpha,
   const double beta,
   double &level,
   double &velocity
)
{
   const double prediction = level + velocity;
   const double errorLimit = atr * InpErrorClipATR;
   const double error = Clamp(price - prediction, -errorLimit, errorLimit);
   level = prediction + alpha * error;
   velocity += beta * error;

   const double velocityLimit = atr * InpMaximumVelocityATR;
   velocity = Clamp(velocity, -velocityLimit, velocityLimit);
}

void UpdateSpines(const double price, const double atr)
{
   if(!g_filterReady)
   {
      g_slowLevel = price;
      g_fastLevel = price;
      g_slowVelocity = 0.0;
      g_fastVelocity = 0.0;
      g_previousSlow = price;
      g_previousSpread = 0.0;
      g_filterReady = true;
      return;
   }

   g_previousSlow = g_slowLevel;
   g_previousSpread = g_fastLevel - g_slowLevel;
   UpdateOneSpine(price, atr, InpSlowAlpha, InpSlowBeta,
                  g_slowLevel, g_slowVelocity);
   UpdateOneSpine(price, atr, InpFastAlpha, InpFastBeta,
                  g_fastLevel, g_fastVelocity);
}

//+------------------------------------------------------------------+
//| Candidate and phase state                                        |
//+------------------------------------------------------------------+
void ClearCandidate()
{
   if(g_candidateIndex >= 0)
   {
      CandidateHLBuffer[g_candidateIndex] = EMPTY_VALUE;
      CandidateLHBuffer[g_candidateIndex] = EMPTY_VALUE;
   }
   g_candidatePrice = 0.0;
   g_candidateTime  = 0;
   g_candidateIndex = -1;
}

void SetCandidate(
   const int direction,
   const int bar,
   const datetime when,
   const double price
)
{
   ClearCandidate();
   g_candidatePrice = price;
   g_candidateTime  = when;
   g_candidateIndex = bar;

   if(InpShowCandidates)
   {
      if(direction > 0)
         CandidateHLBuffer[bar] = price;
      else
         CandidateLHBuffer[bar] = price;
   }
}

void ResetDirectionalPhase(
   const int direction,
   const int bar,
   const datetime &time[],
   const double &high[],
   const double &low[]
)
{
   ClearCandidate();
   g_phase = PHASE_EXPANSION;
   g_excursionPrice = direction > 0 ? high[bar] : low[bar];
   g_excursionTime  = time[bar];
   g_excursionIndex = bar;
   g_excursionDistance = 0.0;
   g_confirmedPivot = 0.0;
   g_confirmedTime  = 0;
   g_confirmedIndex = -1;
   g_validationLevel = 0.0;
}

void ChangeRegime(
   const ENUM_TREND_REGIME next,
   const int bar,
   const datetime &time[],
   const double &high[],
   const double &low[]
)
{
   if(next == g_regime)
      return;

   g_regime = next;
   ClearCandidate();
   g_phase = PHASE_EXPANSION;
   g_confirmedIndex = -1;
   g_validationLevel = 0.0;

   if(next == REGIME_BULL)
   {
      g_lastBullPivot = 0.0;
      ResetDirectionalPhase(1, bar, time, high, low);
   }
   else if(next == REGIME_BEAR)
   {
      g_lastBearPivot = 0.0;
      ResetDirectionalPhase(-1, bar, time, high, low);
   }
   else
   {
      g_excursionIndex = -1;
      g_excursionDistance = 0.0;
      g_lastBullPivot = 0.0;
      g_lastBearPivot = 0.0;
   }
}

void UpdateRegime(
   const int bar,
   const double atr,
   const datetime &time[],
   const double &high[],
   const double &low[],
   const double closePrice
)
{
   const double slowDelta = g_slowLevel - g_previousSlow;
   const double slope = g_slowVelocity / atr;

   if(g_regime == REGIME_NEUTRAL)
   {
      g_bullProgress = MathMax(0.0, g_bullProgress + slowDelta);
      g_bearProgress = MathMax(0.0, g_bearProgress - slowDelta);

      if(slope <= 0.0)
         g_bullProgress *= 0.5;
      if(slope >= 0.0)
         g_bearProgress *= 0.5;

      if(slope >= InpTrendEntrySlopeATR &&
         g_bullProgress >= atr * InpMinimumTrendProgressATR)
      {
         g_bearProgress = 0.0;
         ChangeRegime(REGIME_BULL, bar, time, high, low);
      }
      else if(slope <= -InpTrendEntrySlopeATR &&
              g_bearProgress >= atr * InpMinimumTrendProgressATR)
      {
         g_bullProgress = 0.0;
         ChangeRegime(REGIME_BEAR, bar, time, high, low);
      }
      return;
   }

   if(g_regime == REGIME_BULL)
   {
      const bool slopeFailed = slope < InpTrendHoldSlopeATR;
      const bool priceFailed =
         closePrice < g_slowLevel - atr * InpMaximumPenetrationATR;
      if((slopeFailed && closePrice < g_slowLevel) || priceFailed)
      {
         g_bullProgress = 0.0;
         g_bearProgress = 0.0;
         ChangeRegime(REGIME_NEUTRAL, bar, time, high, low);
      }
   }
   else
   {
      const bool slopeFailed = slope > -InpTrendHoldSlopeATR;
      const bool priceFailed =
         closePrice > g_slowLevel + atr * InpMaximumPenetrationATR;
      if((slopeFailed && closePrice > g_slowLevel) || priceFailed)
      {
         g_bullProgress = 0.0;
         g_bearProgress = 0.0;
         ChangeRegime(REGIME_NEUTRAL, bar, time, high, low);
      }
   }
}

//+------------------------------------------------------------------+
//| Pullback detection                                               |
//+------------------------------------------------------------------+
void StartPullback(
   const int direction,
   const int bar,
   const datetime &time[],
   const double &high[],
   const double &low[]
)
{
   g_phase = PHASE_PULLBACK;
   SetCandidate(direction, bar, time[bar], direction > 0 ? low[bar] : high[bar]);
}

void TrackExpansion(
   const int direction,
   const int bar,
   const double atr,
   const datetime &time[],
   const double &high[],
   const double &low[],
   const double closePrice
)
{
   if(direction > 0 && high[bar] >= g_excursionPrice)
   {
      g_excursionPrice = high[bar];
      g_excursionTime  = time[bar];
      g_excursionIndex = bar;
   }
   if(direction < 0 && low[bar] <= g_excursionPrice)
   {
      g_excursionPrice = low[bar];
      g_excursionTime  = time[bar];
      g_excursionIndex = bar;
   }

   const double distance = direction > 0
      ? (g_excursionPrice - g_slowLevel) / atr
      : (g_slowLevel - g_excursionPrice) / atr;
   g_excursionDistance = MathMax(g_excursionDistance, distance);

   if(bar <= g_excursionIndex ||
      g_excursionDistance < InpMinimumExcursionATR)
      return;

   const double spread = g_fastLevel - g_slowLevel;
   const bool separationContracting = direction > 0
      ? spread < g_previousSpread
      : spread > g_previousSpread;
   const bool nearSpine = direction > 0
      ? low[bar] <= g_slowLevel + atr * InpInnerBandATR
      : high[bar] >= g_slowLevel - atr * InpInnerBandATR;
   const bool fastTurning = direction > 0
      ? (g_fastVelocity <= 0.0 || closePrice < g_fastLevel)
      : (g_fastVelocity >= 0.0 || closePrice > g_fastLevel);

   if(nearSpine && separationContracting && fastTurning)
   {
      StartPullback(direction, bar, time, high, low);
      // A sweep-and-reclaim candle can begin and confirm the rotation.
      // Evaluate it immediately instead of imposing a hidden bar delay.
      TrackPullback(direction, bar, atr, time, high, low, closePrice);
   }
}

int ConfirmationEvidence(
   const int direction,
   const double atr,
   const double closePrice
)
{
   const double spread = g_fastLevel - g_slowLevel;
   const double spreadChange = spread - g_previousSpread;
   int score = 0;

   if(direction > 0)
   {
      if(g_fastVelocity > 0.0) ++score;
      if(spreadChange > 0.0) ++score;
      if(closePrice > g_fastLevel) ++score;
      if(closePrice >= g_candidatePrice + atr * InpCandidateReversalATR) ++score;
   }
   else
   {
      if(g_fastVelocity < 0.0) ++score;
      if(spreadChange < 0.0) ++score;
      if(closePrice < g_fastLevel) ++score;
      if(closePrice <= g_candidatePrice - atr * InpCandidateReversalATR) ++score;
   }
   return(score);
}

void ConfirmCandidate(
   const int direction,
   const int bar,
   const double &high[],
   const double &low[]
)
{
   g_confirmedPivot = g_candidatePrice;
   g_confirmedTime  = g_candidateTime;
   g_confirmedIndex = g_candidateIndex;
   g_validationLevel = g_excursionPrice;

   if(direction > 0)
   {
      HigherLowBuffer[g_confirmedIndex] = g_confirmedPivot;
      if(InpShowConfirmationDots)
         BullConfirmationBuffer[bar] = low[bar];
      g_lastBullPivot = g_confirmedPivot;
   }
   else
   {
      LowerHighBuffer[g_confirmedIndex] = g_confirmedPivot;
      if(InpShowConfirmationDots)
         BearConfirmationBuffer[bar] = high[bar];
      g_lastBearPivot = g_confirmedPivot;
   }

   ClearCandidate();
   g_phase = PHASE_WAIT_VALIDATION;
}

void TrackPullback(
   const int direction,
   const int bar,
   const double atr,
   const datetime &time[],
   const double &high[],
   const double &low[],
   const double closePrice
)
{
   if(direction > 0 && low[bar] < g_candidatePrice)
      SetCandidate(1, bar, time[bar], low[bar]);
   if(direction < 0 && high[bar] > g_candidatePrice)
      SetCandidate(-1, bar, time[bar], high[bar]);

   const bool penetrationFailed = direction > 0
      ? closePrice < g_slowLevel - atr * InpMaximumPenetrationATR
      : closePrice > g_slowLevel + atr * InpMaximumPenetrationATR;
   const bool structureFailed = direction > 0
      ? (g_lastBullPivot > 0.0 && g_candidatePrice <= g_lastBullPivot)
      : (g_lastBearPivot > 0.0 && g_candidatePrice >= g_lastBearPivot);

   if(penetrationFailed || structureFailed)
   {
      if(direction > 0) g_lastBullPivot = 0.0;
      else g_lastBearPivot = 0.0;
      ResetDirectionalPhase(direction, bar, time, high, low);
      return;
   }

   const double pullbackDepth = MathAbs(g_excursionPrice - g_candidatePrice);
   if(pullbackDepth < atr * InpMinimumPullbackATR)
      return;

   if(ConfirmationEvidence(direction, atr, closePrice) >= InpConfirmationScore)
      ConfirmCandidate(direction, bar, high, low);
}

void WaitForValidation(
   const int direction,
   const int bar,
   const datetime &time[],
   const double &high[],
   const double &low[],
   const double closePrice
)
{
   const bool pivotFailed = direction > 0
      ? closePrice <= g_confirmedPivot
      : closePrice >= g_confirmedPivot;

   if(pivotFailed)
   {
      if(direction > 0) g_lastBullPivot = 0.0;
      else g_lastBearPivot = 0.0;
      ResetDirectionalPhase(direction, bar, time, high, low);
      return;
   }

   const bool validated = direction > 0
      ? high[bar] >= g_validationLevel
      : low[bar] <= g_validationLevel;
   if(!validated)
      return;

   if(InpShowValidationDots)
   {
      if(direction > 0) BullValidationBuffer[bar] = high[bar];
      else BearValidationBuffer[bar] = low[bar];
   }

   ResetDirectionalPhase(direction, bar, time, high, low);
}

void ProcessDirectionalState(
   const int bar,
   const double atr,
   const datetime &time[],
   const double &high[],
   const double &low[],
   const double closePrice
)
{
   if(g_regime == REGIME_NEUTRAL)
      return;
   const int direction = (int)g_regime;

   switch(g_phase)
   {
      case PHASE_EXPANSION:
         TrackExpansion(direction, bar, atr, time, high, low, closePrice);
         break;
      case PHASE_PULLBACK:
         TrackPullback(direction, bar, atr, time, high, low, closePrice);
         break;
      case PHASE_WAIT_VALIDATION:
         WaitForValidation(direction, bar, time, high, low, closePrice);
         break;
   }
}

//+------------------------------------------------------------------+
//| Per-bar processing                                               |
//+------------------------------------------------------------------+
void ClearSignalBar(const int bar)
{
   HigherLowBuffer[bar]        = EMPTY_VALUE;
   LowerHighBuffer[bar]        = EMPTY_VALUE;
   BullConfirmationBuffer[bar] = EMPTY_VALUE;
   BearConfirmationBuffer[bar] = EMPTY_VALUE;
   BullValidationBuffer[bar]   = EMPTY_VALUE;
   BearValidationBuffer[bar]   = EMPTY_VALUE;
   CandidateHLBuffer[bar]      = EMPTY_VALUE;
   CandidateLHBuffer[bar]      = EMPTY_VALUE;
}

void ProcessClosedBar(
   const int bar,
   const double atr,
   const datetime &time[],
   const double &open[],
   const double &high[],
   const double &low[],
   const double &close[]
)
{
   ClearSignalBar(bar);
   if(atr <= 0.0 || atr == EMPTY_VALUE)
      return;

   const double price = AppliedPriceAt(bar, open, high, low, close);
   UpdateSpines(price, atr);

   SlowSpineBuffer[bar] = g_slowLevel;
   FastSpineBuffer[bar] = g_fastLevel;
   UpperBandBuffer[bar] = g_slowLevel + atr * InpInnerBandATR;
   LowerBandBuffer[bar] = g_slowLevel - atr * InpInnerBandATR;

   UpdateRegime(bar, atr, time, high, low, close[bar]);
   ProcessDirectionalState(bar, atr, time, high, low, close[bar]);
   g_lastATR = atr;
}

void PublishCurrentBar(const int bar)
{
   SlowSpineBuffer[bar] = g_filterReady ? g_slowLevel : EMPTY_VALUE;
   FastSpineBuffer[bar] = g_filterReady ? g_fastLevel : EMPTY_VALUE;
   UpperBandBuffer[bar] = g_filterReady
      ? g_slowLevel + g_lastATR * InpInnerBandATR : EMPTY_VALUE;
   LowerBandBuffer[bar] = g_filterReady
      ? g_slowLevel - g_lastATR * InpInnerBandATR : EMPTY_VALUE;
   ClearSignalBar(bar);
}

//+------------------------------------------------------------------+
//| Status and history                                               |
//+------------------------------------------------------------------+
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

   string regime = "NEUTRAL";
   if(g_regime == REGIME_BULL) regime = "BULL";
   if(g_regime == REGIME_BEAR) regime = "BEAR";
   string phase = "EXPANSION";
   if(g_phase == PHASE_PULLBACK) phase = "PULLBACK";
   if(g_phase == PHASE_WAIT_VALIDATION) phase = "CONFIRMED";

   ObjectSetString(0, name, OBJPROP_TEXT,
                   "Trend Spine: " + regime + " | " + phase);
   ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(0, name, OBJPROP_ANCHOR, ANCHOR_LEFT_UPPER);
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, 12);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, 18);
   ObjectSetInteger(0, name, OBJPROP_COLOR,
                    g_regime == REGIME_BULL ? clrDeepSkyBlue :
                    (g_regime == REGIME_BEAR ? clrTomato : clrSilver));
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE, 9);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
}

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

void ResetAllState()
{
   g_regime = REGIME_NEUTRAL;
   g_phase = PHASE_EXPANSION;
   g_lastClosedTime = 0;
   g_lastATR = 0.0;
   g_filterReady = false;
   g_slowLevel = 0.0;
   g_slowVelocity = 0.0;
   g_fastLevel = 0.0;
   g_fastVelocity = 0.0;
   g_previousSlow = 0.0;
   g_previousSpread = 0.0;
   g_bullProgress = 0.0;
   g_bearProgress = 0.0;
   g_excursionIndex = -1;
   g_excursionDistance = 0.0;
   g_candidateIndex = -1;
   g_lastBullPivot = 0.0;
   g_lastBearPivot = 0.0;
   g_confirmedIndex = -1;
   g_validationLevel = 0.0;
}

bool RebuildHistory(
   const int lastClosed,
   const datetime &time[],
   const double &open[],
   const double &high[],
   const double &low[],
   const double &close[]
)
{
   ArrayInitialize(SlowSpineBuffer, EMPTY_VALUE);
   ArrayInitialize(FastSpineBuffer, EMPTY_VALUE);
   ArrayInitialize(UpperBandBuffer, EMPTY_VALUE);
   ArrayInitialize(LowerBandBuffer, EMPTY_VALUE);
   ArrayInitialize(HigherLowBuffer, EMPTY_VALUE);
   ArrayInitialize(LowerHighBuffer, EMPTY_VALUE);
   ArrayInitialize(BullConfirmationBuffer, EMPTY_VALUE);
   ArrayInitialize(BearConfirmationBuffer, EMPTY_VALUE);
   ArrayInitialize(BullValidationBuffer, EMPTY_VALUE);
   ArrayInitialize(BearValidationBuffer, EMPTY_VALUE);
   ArrayInitialize(CandidateHLBuffer, EMPTY_VALUE);
   ArrayInitialize(CandidateLHBuffer, EMPTY_VALUE);
   ResetAllState();

   const int start = MathMax(InpATRPeriod, 1);
   if(start >= lastClosed || !CopyAtrRange(start, lastClosed))
      return(false);

   for(int bar = start; bar <= lastClosed && !IsStopped(); ++bar)
   {
      ProcessClosedBar(bar, g_atrSlice[bar - start],
                       time, open, high, low, close);
   }
   g_lastClosedTime = time[lastClosed];
   UpdateStatus();
   return(true);
}

int FindTimeIndex(const datetime value, const int lastClosed,
                  const datetime &time[])
{
   for(int bar = lastClosed; bar >= 0; --bar)
   {
      if(time[bar] == value) return(bar);
      if(time[bar] < value) break;
   }
   return(-1);
}

//+------------------------------------------------------------------+
//| Lifecycle                                                        |
//+------------------------------------------------------------------+
int OnInit()
{
   if(InpATRPeriod < 2 ||
      InpSlowAlpha <= 0.0 || InpSlowAlpha > 1.0 ||
      InpFastAlpha <= 0.0 || InpFastAlpha > 1.0 ||
      InpSlowBeta < 0.0 || InpFastBeta < 0.0 ||
      InpErrorClipATR <= 0.0 || InpMaximumVelocityATR <= 0.0 ||
      InpTrendEntrySlopeATR <= 0.0 ||
      InpTrendHoldSlopeATR < 0.0 ||
      InpMinimumTrendProgressATR <= 0.0 ||
      InpInnerBandATR <= 0.0 || InpMinimumExcursionATR <= 0.0 ||
      InpMinimumPullbackATR <= 0.0 || InpMaximumPenetrationATR <= 0.0 ||
      InpCandidateReversalATR <= 0.0 ||
      InpConfirmationScore < 1 || InpConfirmationScore > 4)
   {
      return(INIT_PARAMETERS_INCORRECT);
   }

   SetIndexBuffer(0, SlowSpineBuffer, INDICATOR_DATA);
   SetIndexBuffer(1, FastSpineBuffer, INDICATOR_DATA);
   SetIndexBuffer(2, UpperBandBuffer, INDICATOR_DATA);
   SetIndexBuffer(3, LowerBandBuffer, INDICATOR_DATA);
   SetIndexBuffer(4, HigherLowBuffer, INDICATOR_DATA);
   SetIndexBuffer(5, LowerHighBuffer, INDICATOR_DATA);
   SetIndexBuffer(6, BullConfirmationBuffer, INDICATOR_DATA);
   SetIndexBuffer(7, BearConfirmationBuffer, INDICATOR_DATA);
   SetIndexBuffer(8, BullValidationBuffer, INDICATOR_DATA);
   SetIndexBuffer(9, BearValidationBuffer, INDICATOR_DATA);
   SetIndexBuffer(10, CandidateHLBuffer, INDICATOR_DATA);
   SetIndexBuffer(11, CandidateLHBuffer, INDICATOR_DATA);

   ArraySetAsSeries(SlowSpineBuffer, false);
   ArraySetAsSeries(FastSpineBuffer, false);
   ArraySetAsSeries(UpperBandBuffer, false);
   ArraySetAsSeries(LowerBandBuffer, false);
   ArraySetAsSeries(HigherLowBuffer, false);
   ArraySetAsSeries(LowerHighBuffer, false);
   ArraySetAsSeries(BullConfirmationBuffer, false);
   ArraySetAsSeries(BearConfirmationBuffer, false);
   ArraySetAsSeries(BullValidationBuffer, false);
   ArraySetAsSeries(BearValidationBuffer, false);
   ArraySetAsSeries(CandidateHLBuffer, false);
   ArraySetAsSeries(CandidateLHBuffer, false);
   ArraySetAsSeries(g_atrSlice, false);

   PlotIndexSetInteger(4, PLOT_ARROW, 233);
   PlotIndexSetInteger(5, PLOT_ARROW, 234);
   PlotIndexSetInteger(6, PLOT_ARROW, 159);
   PlotIndexSetInteger(7, PLOT_ARROW, 159);
   PlotIndexSetInteger(8, PLOT_ARROW, 159);
   PlotIndexSetInteger(9, PLOT_ARROW, 159);
   PlotIndexSetInteger(10, PLOT_ARROW, 241);
   PlotIndexSetInteger(11, PLOT_ARROW, 242);

   for(int plot = 0; plot < 12; ++plot)
   {
      PlotIndexSetDouble(plot, PLOT_EMPTY_VALUE, EMPTY_VALUE);
      PlotIndexSetInteger(plot, PLOT_DRAW_BEGIN, InpATRPeriod);
   }

   g_prefix = "KittTrendSpine_" + InpInstanceTag + "_";
   IndicatorSetInteger(INDICATOR_DIGITS, _Digits);
   IndicatorSetString(INDICATOR_SHORTNAME, "Kitt Trend Spine Pullbacks");

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
   if(rates_total < InpATRPeriod + 4) return(0);

   ArraySetAsSeries(time, false);
   ArraySetAsSeries(open, false);
   ArraySetAsSeries(high, false);
   ArraySetAsSeries(low, false);
   ArraySetAsSeries(close, false);
   ArraySetAsSeries(tick_volume, false);
   ArraySetAsSeries(volume, false);
   ArraySetAsSeries(spread, false);

   const int currentBar = rates_total - 1;
   const int lastClosed = rates_total - 2;
   PublishCurrentBar(currentBar);

   const bool rebuild = prev_calculated == 0 ||
                        prev_calculated > rates_total ||
                        g_lastClosedTime == 0;
   if(rebuild)
   {
      if(!RebuildHistory(lastClosed, time, open, high, low, close)) return(0);
      PublishCurrentBar(currentBar);
      return(rates_total);
   }
   if(time[lastClosed] == g_lastClosedTime) return(rates_total);

   const int priorIndex = FindTimeIndex(g_lastClosedTime, lastClosed, time);
   if(priorIndex < 0)
   {
      if(!RebuildHistory(lastClosed, time, open, high, low, close)) return(0);
      PublishCurrentBar(currentBar);
      return(rates_total);
   }

   const int start = priorIndex + 1;
   if(start <= lastClosed)
   {
      if(!CopyAtrRange(start, lastClosed)) return(prev_calculated);
      for(int bar = start; bar <= lastClosed && !IsStopped(); ++bar)
         ProcessClosedBar(bar, g_atrSlice[bar - start],
                          time, open, high, low, close);
      g_lastClosedTime = time[lastClosed];
      UpdateStatus();
      PublishCurrentBar(currentBar);
      ChartRedraw(0);
   }
   return(rates_total);
}
//+------------------------------------------------------------------+
