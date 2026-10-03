//+------------------------------------------------------------------+
//|                                KittFibPullbackEngine_v1.mq5      |
//|  Structural Fibonacci pullbacks with ATR swing confirmation     |
//|  Rendering base adapted from Fibos_v5_MTF_FAST                  |
//+------------------------------------------------------------------+
#property copyright "Coders' Guru / Kitt adaptation"
#property version   "1.00"
#property strict
#property indicator_chart_window
#property indicator_buffers 10
#property indicator_plots   10

// Eight time-faithful Fibonacci buffers for iCustom/Data Window.
// Chart geometry is drawn once with finite objects to avoid duplicate lines.
#property indicator_label1  "Fib 0.0%"
#property indicator_type1   DRAW_NONE
#property indicator_label2  "Fib 23.6%"
#property indicator_type2   DRAW_NONE
#property indicator_label3  "Fib 38.2%"
#property indicator_type3   DRAW_NONE
#property indicator_label4  "Fib 50.0%"
#property indicator_type4   DRAW_NONE
#property indicator_label5  "Fib 61.8%"
#property indicator_type5   DRAW_NONE
#property indicator_label6  "Fib 78.6%"
#property indicator_type6   DRAW_NONE
#property indicator_label7  "Fib 90.0%"
#property indicator_type7   DRAW_NONE
#property indicator_label8  "Fib 100.0%"
#property indicator_type8   DRAW_NONE

#property indicator_label9  "Bull Pullback Confirmation"
#property indicator_type9   DRAW_ARROW
#property indicator_color9  clrLimeGreen
#property indicator_width9  2

#property indicator_label10 "Bear Pullback Confirmation"
#property indicator_type10  DRAW_ARROW
#property indicator_color10 clrTomato
#property indicator_width10 2

input group "ATR Structural Swing Engine"
input int    InpSwingATRPeriod       = 14;
input double InpSwingReversalATR     = 1.00;
input int    InpMinBarsBetweenPivots = 1;

input group "Impulse and Pullback"
input double InpMinimumImpulseATR    = 1.50;
input double InpConfirmationATR      = 0.50;
input bool   InpRequireClosePast618  = true;
input bool   InpShowDevelopingFib    = true;
input bool   InpPause                = false;

input group "Finite Level Display"
input string InpInstanceTag          = "Main";
input int    InpExtendBarsRight      = 20;
input bool   InpShowLevelLabels      = true;
input bool   InpShowZones            = true;
input int    InpLevelLineWidth       = 1;

input group "Colors"
input color InpBullColor             = clrLimeGreen;
input color InpBearColor             = clrTomato;
input color InpPrimaryZoneColor      = C'32,72,48';
input color InpDeepZoneColor         = C'72,54,32';
input color InpFib0Color             = clrSilver;
input color InpFib236Color           = clrDeepSkyBlue;
input color InpFib382Color           = clrDodgerBlue;
input color InpFib500Color           = clrGold;
input color InpFib618Color           = clrOrange;
input color InpFib786Color           = clrOrangeRed;
input color InpFib900Color           = clrViolet;
input color InpFib100Color           = clrSilver;

double Fib0Buffer[];
double Fib236Buffer[];
double Fib382Buffer[];
double Fib500Buffer[];
double Fib618Buffer[];
double Fib786Buffer[];
double Fib900Buffer[];
double Fib100Buffer[];
double BullSignalBuffer[];
double BearSignalBuffer[];
double g_atrSlice[];

double g_factors[8];
double g_levels[8];

enum ENUM_SWING_STATE
{
   SWING_UNINITIALIZED = 0,
   SWING_TRACK_HIGH    = 1,
   SWING_TRACK_LOW     = -1
};

ENUM_SWING_STATE g_swingState = SWING_UNINITIALIZED;

int      g_atrHandle       = INVALID_HANDLE;
int      g_extremeIndex    = -1;
int      g_lastPivotIndex  = -1;
double   g_extremePrice    = 0.0;
datetime g_extremeTime     = 0;
datetime g_lastClosedTime  = 0;
double   g_lastATR         = 0.0;

double   g_high1 = 0.0;
double   g_high2 = 0.0;
double   g_low1  = 0.0;
double   g_low2  = 0.0;
datetime g_high1Time = 0;
datetime g_high2Time = 0;
datetime g_low1Time  = 0;
datetime g_low2Time  = 0;
int      g_high1Index = -1;
int      g_high2Index = -1;
int      g_low1Index  = -1;
int      g_low2Index  = -1;

bool     g_haveImpulse       = false;
bool     g_impulseLocked     = false;
int      g_activeDirection   = 0;
double   g_originPrice       = 0.0;
double   g_impulsePrice      = 0.0;
datetime g_originTime        = 0;
datetime g_impulseTime       = 0;
int      g_originIndex       = -1;
int      g_impulseIndex      = -1;

bool   g_pullbackArmed   = false;
bool   g_signalFired     = false;
double g_pullbackExtreme = 0.0;
int    g_pullbackIndex   = -1;

string g_prefix = "KittFibPB_";

//+------------------------------------------------------------------+
//| Buffer and level setup                                           |
//+------------------------------------------------------------------+
void SetupLevelPlot(
   const int index,
   double &buffer[],
   const color lineColor,
   const string label
)
{
   SetIndexBuffer(index, buffer, INDICATOR_DATA);
   ArraySetAsSeries(buffer, false);
   PlotIndexSetInteger(index, PLOT_DRAW_TYPE, DRAW_NONE);
   PlotIndexSetInteger(index, PLOT_LINE_COLOR, lineColor);
   PlotIndexSetDouble(index, PLOT_EMPTY_VALUE, EMPTY_VALUE);
   PlotIndexSetString(index, PLOT_LABEL, label);
}

void BuildFactorTable()
{
   g_factors[0] = 0.000;
   g_factors[1] = 0.236;
   g_factors[2] = 0.382;
   g_factors[3] = 0.500;
   g_factors[4] = 0.618;
   g_factors[5] = 0.786;
   g_factors[6] = 0.900;
   g_factors[7] = 1.000;
}

color LevelColor(const int index)
{
   switch(index)
   {
      case 0: return InpFib0Color;
      case 1: return InpFib236Color;
      case 2: return InpFib382Color;
      case 3: return InpFib500Color;
      case 4: return InpFib618Color;
      case 5: return InpFib786Color;
      case 6: return InpFib900Color;
      case 7: return InpFib100Color;
   }
   return(clrWhite);
}

void ClearLevelBuffers()
{
   ArrayInitialize(Fib0Buffer,   EMPTY_VALUE);
   ArrayInitialize(Fib236Buffer, EMPTY_VALUE);
   ArrayInitialize(Fib382Buffer, EMPTY_VALUE);
   ArrayInitialize(Fib500Buffer, EMPTY_VALUE);
   ArrayInitialize(Fib618Buffer, EMPTY_VALUE);
   ArrayInitialize(Fib786Buffer, EMPTY_VALUE);
   ArrayInitialize(Fib900Buffer, EMPTY_VALUE);
   ArrayInitialize(Fib100Buffer, EMPTY_VALUE);
}

void SetLevelAt(const int index, const int bar, const double value)
{
   switch(index)
   {
      case 0: Fib0Buffer[bar]   = value; break;
      case 1: Fib236Buffer[bar] = value; break;
      case 2: Fib382Buffer[bar] = value; break;
      case 3: Fib500Buffer[bar] = value; break;
      case 4: Fib618Buffer[bar] = value; break;
      case 5: Fib786Buffer[bar] = value; break;
      case 6: Fib900Buffer[bar] = value; break;
      case 7: Fib100Buffer[bar] = value; break;
   }
}

void PublishLevelsAt(const int bar)
{
   for(int level = 0; level < 8; ++level)
      SetLevelAt(level, bar, g_haveImpulse ? g_levels[level] : EMPTY_VALUE);
}

void BuildLevelPrices()
{
   const double range = MathAbs(g_impulsePrice - g_originPrice);

   for(int level = 0; level < 8; ++level)
   {
      if(g_activeDirection > 0)
         g_levels[level] = g_impulsePrice - range * g_factors[level];
      else
         g_levels[level] = g_impulsePrice + range * g_factors[level];
   }
}

//+------------------------------------------------------------------+
//| State                                                            |
//+------------------------------------------------------------------+
void ResetPullbackState()
{
   g_pullbackArmed   = false;
   g_signalFired     = false;
   g_pullbackExtreme = 0.0;
   g_pullbackIndex   = -1;
}

void ResetAllState()
{
   g_swingState      = SWING_UNINITIALIZED;
   g_extremeIndex    = -1;
   g_lastPivotIndex  = -1;
   g_extremePrice    = 0.0;
   g_extremeTime     = 0;
   g_lastClosedTime  = 0;
   g_lastATR         = 0.0;

   g_high1 = 0.0;
   g_high2 = 0.0;
   g_low1  = 0.0;
   g_low2  = 0.0;
   g_high1Time = 0;
   g_high2Time = 0;
   g_low1Time  = 0;
   g_low2Time  = 0;
   g_high1Index = -1;
   g_high2Index = -1;
   g_low1Index  = -1;
   g_low2Index  = -1;

   g_haveImpulse     = false;
   g_impulseLocked   = false;
   g_activeDirection = 0;
   g_originPrice     = 0.0;
   g_impulsePrice    = 0.0;
   g_originTime      = 0;
   g_impulseTime     = 0;
   g_originIndex     = -1;
   g_impulseIndex    = -1;
   ResetPullbackState();
}

void RecordHigh(
   const double price,
   const datetime when,
   const int index
)
{
   g_high2      = g_high1;
   g_high2Time  = g_high1Time;
   g_high2Index = g_high1Index;
   g_high1      = price;
   g_high1Time  = when;
   g_high1Index = index;
}

void RecordLow(
   const double price,
   const datetime when,
   const int index
)
{
   g_low2      = g_low1;
   g_low2Time  = g_low1Time;
   g_low2Index = g_low1Index;
   g_low1      = price;
   g_low1Time  = when;
   g_low1Index = index;
}

int StructureDirection()
{
   if(g_high2Index < 0 || g_low2Index < 0)
      return(0);

   if(g_high1 > g_high2 && g_low1 > g_low2)
      return(1);

   if(g_high1 < g_high2 && g_low1 < g_low2)
      return(-1);

   return(0);
}

//+------------------------------------------------------------------+
//| ATR access                                                       |
//+------------------------------------------------------------------+
bool CopyAtrRange(const int start, const int lastClosed)
{
   const int count = lastClosed - start + 1;
   if(count <= 0)
      return(false);

   if(ArrayResize(g_atrSlice, count) != count)
      return(false);

   ResetLastError();
   const int copied = CopyBuffer(g_atrHandle, 0, 1, count, g_atrSlice);

   if(copied != count)
   {
      PrintFormat(
         "ATR not ready: requested %d, copied %d, error %d",
         count,
         copied,
         GetLastError()
      );
      return(false);
   }

   return(true);
}

//+------------------------------------------------------------------+
//| Swing, impulse, and confirmation logic                           |
//+------------------------------------------------------------------+
void InitializeSwingTracker(
   const int start,
   const datetime &time[],
   const double &high[],
   const double &low[],
   const double &close[]
)
{
   g_swingState =
      (close[start] >= close[start - 1])
      ? SWING_TRACK_HIGH
      : SWING_TRACK_LOW;

   g_extremeIndex = start;
   g_extremeTime  = time[start];
   g_extremePrice =
      (g_swingState == SWING_TRACK_HIGH)
      ? high[start]
      : low[start];
}

void AdvanceSwingState(
   const int bar,
   const double atr,
   const datetime &time[],
   const double &high[],
   const double &low[],
   const double &close[]
)
{
   const double reversal = atr * InpSwingReversalATR;

   if(g_swingState == SWING_TRACK_HIGH)
   {
      if(high[bar] >= g_extremePrice)
      {
         g_extremePrice = high[bar];
         g_extremeTime  = time[bar];
         g_extremeIndex = bar;
      }

      const bool enoughBars =
         g_lastPivotIndex < 0 ||
         (bar - g_lastPivotIndex) >= InpMinBarsBetweenPivots;

      if(enoughBars && close[bar] <= g_extremePrice - reversal)
      {
         RecordHigh(g_extremePrice, g_extremeTime, g_extremeIndex);
         g_lastPivotIndex = g_extremeIndex;
         g_swingState     = SWING_TRACK_LOW;
         g_extremePrice   = low[bar];
         g_extremeTime    = time[bar];
         g_extremeIndex   = bar;
      }
   }
   else if(g_swingState == SWING_TRACK_LOW)
   {
      if(low[bar] <= g_extremePrice)
      {
         g_extremePrice = low[bar];
         g_extremeTime  = time[bar];
         g_extremeIndex = bar;
      }

      const bool enoughBars =
         g_lastPivotIndex < 0 ||
         (bar - g_lastPivotIndex) >= InpMinBarsBetweenPivots;

      if(enoughBars && close[bar] >= g_extremePrice + reversal)
      {
         RecordLow(g_extremePrice, g_extremeTime, g_extremeIndex);
         g_lastPivotIndex = g_extremeIndex;
         g_swingState     = SWING_TRACK_HIGH;
         g_extremePrice   = high[bar];
         g_extremeTime    = time[bar];
         g_extremeIndex   = bar;
      }
   }
}

void DisableImpulse(const bool resetPullback)
{
   g_haveImpulse = false;
   if(resetPullback)
      ResetPullbackState();
}

void RefreshActiveImpulse(
   const int bar,
   const double atr,
   const double closePrice
)
{
   const int direction = StructureDirection();

   if(direction == 0)
   {
      g_activeDirection = 0;
      DisableImpulse(true);
      return;
   }

   double originPrice;
   double impulsePrice;
   datetime originTime;
   datetime impulseTime;
   int originIndex;
   int impulseIndex;
   bool locked;

   if(direction > 0)
   {
      originPrice = g_low1;
      originTime  = g_low1Time;
      originIndex = g_low1Index;

      locked = (g_swingState == SWING_TRACK_LOW);
      if(locked)
      {
         impulsePrice = g_high1;
         impulseTime  = g_high1Time;
         impulseIndex = g_high1Index;
      }
      else
      {
         impulsePrice = g_extremePrice;
         impulseTime  = g_extremeTime;
         impulseIndex = g_extremeIndex;
      }
   }
   else
   {
      originPrice = g_high1;
      originTime  = g_high1Time;
      originIndex = g_high1Index;

      locked = (g_swingState == SWING_TRACK_HIGH);
      if(locked)
      {
         impulsePrice = g_low1;
         impulseTime  = g_low1Time;
         impulseIndex = g_low1Index;
      }
      else
      {
         impulsePrice = g_extremePrice;
         impulseTime  = g_extremeTime;
         impulseIndex = g_extremeIndex;
      }
   }

   const bool ordered =
      originIndex >= 0 &&
      impulseIndex > originIndex &&
      impulseTime > originTime;

   const bool priceOrdered =
      direction > 0
      ? impulsePrice > originPrice
      : impulsePrice < originPrice;

   if(!ordered || !priceOrdered)
   {
      g_activeDirection = direction;
      DisableImpulse(true);
      return;
   }

   const bool newLeg =
      direction != g_activeDirection ||
      originTime != g_originTime ||
      originIndex != g_originIndex;

   if(newLeg)
      ResetPullbackState();

   g_activeDirection = direction;
   g_originPrice     = originPrice;
   g_originTime      = originTime;
   g_originIndex     = originIndex;
   g_impulsePrice    = impulsePrice;
   g_impulseTime     = impulseTime;
   g_impulseIndex    = impulseIndex;
   g_impulseLocked   = locked;

   const double range = MathAbs(impulsePrice - originPrice);
   const bool invalidated =
      direction > 0
      ? closePrice <= originPrice
      : closePrice >= originPrice;

   g_haveImpulse =
      !invalidated &&
      range >= atr * InpMinimumImpulseATR &&
      (locked || InpShowDevelopingFib);

   if(!g_haveImpulse)
   {
      if(invalidated)
         ResetPullbackState();
      return;
   }

   BuildLevelPrices();
}

void EvaluatePullback(
   const int bar,
   const double atr,
   const double &high[],
   const double &low[],
   const double &close[]
)
{
   if(!g_haveImpulse || g_signalFired || bar <= g_impulseIndex)
      return;

   const double zoneA = g_levels[2]; // 38.2%
   const double zoneB = g_levels[5]; // 78.6%
   const double zoneTop = MathMax(zoneA, zoneB);
   const double zoneBottom = MathMin(zoneA, zoneB);

   const bool overlapsZone =
      low[bar] <= zoneTop &&
      high[bar] >= zoneBottom;

   if(!g_pullbackArmed && overlapsZone)
   {
      g_pullbackArmed = true;
      g_pullbackIndex = bar;
      g_pullbackExtreme =
         (g_activeDirection > 0)
         ? low[bar]
         : high[bar];
   }

   if(!g_pullbackArmed)
      return;

   if(g_activeDirection > 0)
   {
      if(low[bar] < g_pullbackExtreme)
      {
         g_pullbackExtreme = low[bar];
         g_pullbackIndex   = bar;
      }

      const bool volatilityReversal =
         close[bar] >= g_pullbackExtreme + atr * InpConfirmationATR;

      const bool levelReclaim =
         !InpRequireClosePast618 ||
         close[bar] >= g_levels[4];

      if(volatilityReversal && levelReclaim)
      {
         BullSignalBuffer[bar] = low[bar];
         g_signalFired = true;
      }
   }
   else
   {
      if(high[bar] > g_pullbackExtreme)
      {
         g_pullbackExtreme = high[bar];
         g_pullbackIndex   = bar;
      }

      const bool volatilityReversal =
         close[bar] <= g_pullbackExtreme - atr * InpConfirmationATR;

      const bool levelReclaim =
         !InpRequireClosePast618 ||
         close[bar] <= g_levels[4];

      if(volatilityReversal && levelReclaim)
      {
         BearSignalBuffer[bar] = high[bar];
         g_signalFired = true;
      }
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
   BullSignalBuffer[bar] = EMPTY_VALUE;
   BearSignalBuffer[bar] = EMPTY_VALUE;

   if(atr <= 0.0 || atr == EMPTY_VALUE)
   {
      PublishLevelsAt(bar);
      return;
   }

   AdvanceSwingState(bar, atr, time, high, low, close);
   RefreshActiveImpulse(bar, atr, close[bar]);
   EvaluatePullback(bar, atr, high, low, close);
   PublishLevelsAt(bar);
   g_lastATR = atr;
}

//+------------------------------------------------------------------+
//| Finite object rendering                                          |
//+------------------------------------------------------------------+
string ObjName(const string suffix)
{
   return(g_prefix + suffix);
}

void DeleteObject(const string suffix)
{
   const string name = ObjName(suffix);
   if(ObjectFind(0, name) >= 0)
      ObjectDelete(0, name);
}

void DeleteGeometryObjects()
{
   DeleteObject("IMPULSE");
   DeleteObject("ORIGIN");
   DeleteObject("EXTREME");
   DeleteObject("PRIMARY_ZONE");
   DeleteObject("DEEP_ZONE");

   for(int level = 0; level < 8; ++level)
   {
      DeleteObject("LEVEL_" + IntegerToString(level));
      DeleteObject("LABEL_" + IntegerToString(level));
   }
}

void DeleteOwnObjects()
{
   ObjectsDeleteAll(0, g_prefix, -1, -1);
}

void EnsureVerticalLine(
   const string suffix,
   const datetime when,
   const color lineColor
)
{
   const string name = ObjName(suffix);
   if(ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_VLINE, 0, when, 0.0);
   else
      ObjectMove(0, name, 0, when, 0.0);

   ObjectSetInteger(0, name, OBJPROP_COLOR, lineColor);
   ObjectSetInteger(0, name, OBJPROP_STYLE, STYLE_DASH);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, 1);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
}

void EnsureTrend(
   const datetime t1,
   const double p1,
   const datetime t2,
   const double p2,
   const color lineColor
)
{
   const string name = ObjName("IMPULSE");
   if(ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_TREND, 0, t1, p1, t2, p2);
   else
   {
      ObjectMove(0, name, 0, t1, p1);
      ObjectMove(0, name, 1, t2, p2);
   }

   ObjectSetInteger(0, name, OBJPROP_RAY_RIGHT, false);
   ObjectSetInteger(0, name, OBJPROP_COLOR, lineColor);
   ObjectSetInteger(0, name, OBJPROP_STYLE, STYLE_DASH);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, 1);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
}

void EnsureLevelLine(
   const int level,
   const datetime t1,
   const datetime t2,
   const double price
)
{
   const string name = ObjName("LEVEL_" + IntegerToString(level));
   if(ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_TREND, 0, t1, price, t2, price);
   else
   {
      ObjectMove(0, name, 0, t1, price);
      ObjectMove(0, name, 1, t2, price);
   }

   ObjectSetInteger(0, name, OBJPROP_RAY_LEFT, false);
   ObjectSetInteger(0, name, OBJPROP_RAY_RIGHT, false);
   ObjectSetInteger(0, name, OBJPROP_COLOR, LevelColor(level));
   ObjectSetInteger(0, name, OBJPROP_STYLE, STYLE_SOLID);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, MathMax(InpLevelLineWidth, 1));
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
}

void EnsureLevelLabel(
   const int level,
   const datetime when,
   const double price
)
{
   const string name = ObjName("LABEL_" + IntegerToString(level));

   if(!InpShowLevelLabels)
   {
      if(ObjectFind(0, name) >= 0)
         ObjectDelete(0, name);
      return;
   }

   if(ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_TEXT, 0, when, price);
   else
      ObjectMove(0, name, 0, when, price);

   string state = g_impulseLocked ? "L" : "D";
   ObjectSetString(
      0,
      name,
      OBJPROP_TEXT,
      state + " " + DoubleToString(g_factors[level] * 100.0, 1) + "%"
   );
   ObjectSetInteger(0, name, OBJPROP_COLOR, LevelColor(level));
   ObjectSetInteger(0, name, OBJPROP_ANCHOR, ANCHOR_LEFT);
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE, 8);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
}

void EnsureZone(
   const string suffix,
   const datetime t1,
   const datetime t2,
   const double priceA,
   const double priceB,
   const color zoneColor
)
{
   const string name = ObjName(suffix);

   if(!InpShowZones)
   {
      if(ObjectFind(0, name) >= 0)
         ObjectDelete(0, name);
      return;
   }

   const double top = MathMax(priceA, priceB);
   const double bottom = MathMin(priceA, priceB);

   if(ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_RECTANGLE, 0, t1, top, t2, bottom);
   else
   {
      ObjectMove(0, name, 0, t1, top);
      ObjectMove(0, name, 1, t2, bottom);
   }

   ObjectSetInteger(0, name, OBJPROP_COLOR, zoneColor);
   ObjectSetInteger(0, name, OBJPROP_FILL, true);
   ObjectSetInteger(0, name, OBJPROP_BACK, true);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
}

void EnsureStatusLabel()
{
   const string name = ObjName("STATUS");
   if(ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0);

   string text = "Kitt Fib Pullback: waiting for structure";
   color textColor = clrSilver;

   if(g_haveImpulse)
   {
      const string direction = g_activeDirection > 0 ? "BULL" : "BEAR";
      const string state = g_impulseLocked ? "LOCKED" : "DEVELOPING";
      const string pullback =
         g_signalFired
         ? "CONFIRMED"
         : (g_pullbackArmed ? "ARMED" : "WAITING");

      text =
         "Kitt Fib Pullback: " + direction +
         " | " + state +
         " | " + pullback;
      textColor = g_activeDirection > 0 ? InpBullColor : InpBearColor;
   }

   ObjectSetString(0, name, OBJPROP_TEXT, text);
   ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(0, name, OBJPROP_ANCHOR, ANCHOR_LEFT_UPPER);
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, 12);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, 18);
   ObjectSetInteger(0, name, OBJPROP_COLOR, textColor);
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE, 9);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
}

void UpdateObjects()
{
   EnsureStatusLabel();

   if(!g_haveImpulse)
   {
      DeleteGeometryObjects();
      ChartRedraw(0);
      return;
   }

   const color directionColor =
      g_activeDirection > 0 ? InpBullColor : InpBearColor;

   datetime currentTime = iTime(_Symbol, PERIOD_CURRENT, 0);
   if(currentTime <= 0)
      currentTime = TimeCurrent();

   const int seconds = MathMax(PeriodSeconds(PERIOD_CURRENT), 1);
   datetime levelEnd =
      currentTime + (datetime)(MathMax(InpExtendBarsRight, 0) * seconds);

   if(levelEnd <= g_impulseTime)
      levelEnd = g_impulseTime + (datetime)seconds;

   EnsureVerticalLine("ORIGIN", g_originTime, directionColor);
   EnsureVerticalLine("EXTREME", g_impulseTime, directionColor);
   EnsureTrend(
      g_originTime,
      g_originPrice,
      g_impulseTime,
      g_impulsePrice,
      directionColor
   );

   for(int level = 0; level < 8; ++level)
   {
      EnsureLevelLine(level, g_impulseTime, levelEnd, g_levels[level]);
      EnsureLevelLabel(level, levelEnd, g_levels[level]);
   }

   EnsureZone(
      "PRIMARY_ZONE",
      g_impulseTime,
      levelEnd,
      g_levels[2],
      g_levels[4],
      InpPrimaryZoneColor
   );

   EnsureZone(
      "DEEP_ZONE",
      g_impulseTime,
      levelEnd,
      g_levels[4],
      g_levels[5],
      InpDeepZoneColor
   );

   ChartRedraw(0);
}

//+------------------------------------------------------------------+
//| Historical and incremental calculation                           |
//+------------------------------------------------------------------+
bool RebuildHistory(
   const int lastClosed,
   const datetime &time[],
   const double &high[],
   const double &low[],
   const double &close[]
)
{
   ClearLevelBuffers();
   ArrayInitialize(BullSignalBuffer, EMPTY_VALUE);
   ArrayInitialize(BearSignalBuffer, EMPTY_VALUE);
   ResetAllState();

   const int start = MathMax(InpSwingATRPeriod, 1);
   if(start >= lastClosed || !CopyAtrRange(start, lastClosed))
      return(false);

   InitializeSwingTracker(start, time, high, low, close);
   PublishLevelsAt(start);

   for(int bar = start + 1; bar <= lastClosed && !IsStopped(); ++bar)
   {
      ProcessClosedBar(
         bar,
         g_atrSlice[bar - start],
         time,
         high,
         low,
         close
      );
   }

   g_lastClosedTime = time[lastClosed];
   UpdateObjects();
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
//| Initialization                                                   |
//+------------------------------------------------------------------+
int OnInit()
{
   if(InpSwingATRPeriod < 2 ||
      InpSwingReversalATR <= 0.0 ||
      InpMinBarsBetweenPivots < 1 ||
      InpMinimumImpulseATR <= 0.0 ||
      InpConfirmationATR <= 0.0 ||
      InpExtendBarsRight < 0)
   {
      return(INIT_PARAMETERS_INCORRECT);
   }

   BuildFactorTable();
   g_prefix = "KittFibPB_" + InpInstanceTag + "_";

   SetupLevelPlot(0, Fib0Buffer,   InpFib0Color,   "Fib_0.000");
   SetupLevelPlot(1, Fib236Buffer, InpFib236Color, "Fib_0.236");
   SetupLevelPlot(2, Fib382Buffer, InpFib382Color, "Fib_0.382");
   SetupLevelPlot(3, Fib500Buffer, InpFib500Color, "Fib_0.500");
   SetupLevelPlot(4, Fib618Buffer, InpFib618Color, "Fib_0.618");
   SetupLevelPlot(5, Fib786Buffer, InpFib786Color, "Fib_0.786");
   SetupLevelPlot(6, Fib900Buffer, InpFib900Color, "Fib_0.900");
   SetupLevelPlot(7, Fib100Buffer, InpFib100Color, "Fib_1.000");

   SetIndexBuffer(8, BullSignalBuffer, INDICATOR_DATA);
   SetIndexBuffer(9, BearSignalBuffer, INDICATOR_DATA);
   ArraySetAsSeries(BullSignalBuffer, false);
   ArraySetAsSeries(BearSignalBuffer, false);
   ArraySetAsSeries(g_atrSlice, false);

   PlotIndexSetInteger(8, PLOT_ARROW, 233);
   PlotIndexSetInteger(9, PLOT_ARROW, 234);
   PlotIndexSetDouble(8, PLOT_EMPTY_VALUE, EMPTY_VALUE);
   PlotIndexSetDouble(9, PLOT_EMPTY_VALUE, EMPTY_VALUE);
   PlotIndexSetInteger(8, PLOT_DRAW_BEGIN, InpSwingATRPeriod + 1);
   PlotIndexSetInteger(9, PLOT_DRAW_BEGIN, InpSwingATRPeriod + 1);

   IndicatorSetInteger(INDICATOR_DIGITS, _Digits);
   IndicatorSetString(
      INDICATOR_SHORTNAME,
      StringFormat(
         "Kitt Fib Pullback Engine (%d, %.2f ATR)",
         InpSwingATRPeriod,
         InpSwingReversalATR
      )
   );

   g_atrHandle = iATR(_Symbol, PERIOD_CURRENT, InpSwingATRPeriod);
   if(g_atrHandle == INVALID_HANDLE)
   {
      PrintFormat("Unable to create ATR handle. Error %d", GetLastError());
      return(INIT_FAILED);
   }

   DeleteOwnObjects();
   ResetAllState();
   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason)
{
   DeleteOwnObjects();

   if(g_atrHandle != INVALID_HANDLE)
   {
      IndicatorRelease(g_atrHandle);
      g_atrHandle = INVALID_HANDLE;
   }
}

//+------------------------------------------------------------------+
//| Calculation                                                      |
//+------------------------------------------------------------------+
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
   if(rates_total < InpSwingATRPeriod + 4)
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

   BullSignalBuffer[currentBar] = EMPTY_VALUE;
   BearSignalBuffer[currentBar] = EMPTY_VALUE;

   const bool mustRebuild =
      prev_calculated == 0 ||
      prev_calculated > rates_total ||
      g_lastClosedTime == 0;

   if(mustRebuild)
   {
      if(!RebuildHistory(lastClosed, time, high, low, close))
         return(0);

      PublishLevelsAt(currentBar);
      return(rates_total);
   }

   if(InpPause)
   {
      PublishLevelsAt(currentBar);
      return(rates_total);
   }

   if(time[lastClosed] == g_lastClosedTime)
   {
      PublishLevelsAt(currentBar);
      return(rates_total);
   }

   const int priorIndex = FindTimeIndex(g_lastClosedTime, lastClosed, time);
   if(priorIndex < 0)
   {
      if(!RebuildHistory(lastClosed, time, high, low, close))
         return(0);

      PublishLevelsAt(currentBar);
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
            time,
            high,
            low,
            close
         );
      }

      g_lastClosedTime = time[lastClosed];
      UpdateObjects();
   }

   PublishLevelsAt(currentBar);
   return(rates_total);
}
//+------------------------------------------------------------------+
