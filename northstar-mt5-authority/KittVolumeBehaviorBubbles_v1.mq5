//+------------------------------------------------------------------+
//|                   KittVolumeBehaviorBubbles_v1.mq5               |
//| Lower-timeframe abnormal-volume location and behavior proxy      |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026, Indices Group (Pty) Ltd"
#property link      "https://indices-investment-group.thinkific.com"
#property version   "1.20"
#property description "Maps abnormal lower-timeframe volume onto the chart."
#property description "Smart/Retail labels are behavior proxies, not trader identity."

#property indicator_chart_window
#property indicator_buffers 1
#property indicator_plots   1
#property indicator_type1   DRAW_NONE

#include <Canvas\Canvas.mqh>

enum ENUM_KITT_PARTICIPANT
{
   KITT_SHOW_BOTH = 0,
   KITT_SHOW_SMART_PROXY,
   KITT_SHOW_RETAIL_PROXY
};

enum ENUM_KITT_BUBBLE_MODE
{
   KITT_BUBBLE_FILLED = 0,
   KITT_BUBBLE_OUTLINE
};

enum ENUM_KITT_VOLUME_SOURCE
{
   KITT_VOLUME_AUTO = 0,
   KITT_VOLUME_TICK,
   KITT_VOLUME_REAL
};

//--- Detection
input group "Detection"
input ENUM_TIMEFRAMES       InpLowerTimeframe       = PERIOD_M5;
input int                   InpPeriodChartBars      = 20;
input double                InpZThreshold           = 2.00;
input bool                  InpPositiveSpikesOnly   = true;
input ENUM_KITT_VOLUME_SOURCE InpVolumeSource       = KITT_VOLUME_AUTO;
input int                   InpMaxBarsToCalculate   = 500;  // 0 = all loaded bars
input int                   InpMaxRenderedBubbles   = 150;

//--- Behavioral classification
input group "Behavior Proxy"
input ENUM_KITT_PARTICIPANT InpWhoToShow            = KITT_SHOW_BOTH;
input double                InpExtremeFraction      = 0.25;

//--- Display
input group "Display"
input bool                  InpShowBubbles          = true;
input bool                  InpShowLevels           = true;
input bool                  InpShowScorecard        = true;
input ENUM_KITT_BUBBLE_MODE InpBubbleMode           = KITT_BUBBLE_FILLED;
input bool                  InpObjectsInBackground  = false;
input int                   InpTransparency         = 18;
input int                   InpMinimumBubbleSize    = 8;
input int                   InpMaximumBubbleSize    = 48;
input double                InpZSizeCap             = 6.0;
input color                 InpSmartBullColor       = clrLimeGreen;
input color                 InpSmartBearColor       = clrCrimson;
input color                 InpRetailBullColor      = clrDeepSkyBlue;
input color                 InpRetailBearColor      = clrOrangeRed;

//--- Scorecard
input group "Scorecard"
input ENUM_BASE_CORNER      InpPanelCorner          = CORNER_RIGHT_UPPER;
input int                   InpPanelX                = 18;
input int                   InpPanelY                = 28;
input int                   InpScorecardRefreshMs   = 250;
input color                 InpPanelTextColor       = clrWhite;
input color                 InpPanelBackground      = clrBlack;
input string                InpUniqueId              = "01";

double DummyBuffer[];

enum ENUM_KITT_CLASS
{
   KITT_RETAIL_CLASS = 0,
   KITT_SMART_CLASS  = 1
};

struct BubbleEvent
{
   datetime time;
   double   price;
   double   z;
   double   volume;
   int      participant;
   int      direction;
};

BubbleEvent    g_events[];
string         g_prefix              = "";
ENUM_TIMEFRAMES g_lowerTf            = PERIOD_CURRENT;
bool           g_usedRealVolume      = false;
bool           g_usedTickVolume      = false;
int            g_detectedTotal       = 0;
datetime       g_renderedLevelTimes[];
uint           g_lastScorecardMs     = 0;
bool           g_renderingEnabled    = true;
CCanvas        g_bubbleCanvas;
bool           g_canvasReady         = false;
int            g_canvasWidth         = 0;
int            g_canvasHeight        = 0;

//+------------------------------------------------------------------+
int OnInit()
{
   SetIndexBuffer(0, DummyBuffer, INDICATOR_DATA);
   ArraySetAsSeries(DummyBuffer, false);

   g_lowerTf = InpLowerTimeframe;
   const int chartSeconds = PeriodSeconds(_Period);
   const int lowerSeconds = PeriodSeconds(g_lowerTf);

   if(chartSeconds <= 0 || lowerSeconds <= 0 || lowerSeconds >= chartSeconds)
   {
      Print("Kitt Volume Bubbles: lower timeframe must be below chart timeframe.");
      return(INIT_PARAMETERS_INCORRECT);
   }
   if(InpPeriodChartBars < 2 || InpZThreshold <= 0.0 ||
      InpMaxRenderedBubbles < 1 || InpMinimumBubbleSize < 1 ||
      InpMaximumBubbleSize < InpMinimumBubbleSize ||
      InpExtremeFraction < 0.0 || InpExtremeFraction > 0.5 ||
      InpTransparency < 0 || InpTransparency > 100 ||
      InpScorecardRefreshMs < 0 ||
      InpZSizeCap <= InpZThreshold)
   {
      Print("Kitt Volume Bubbles: invalid input combination.");
      return(INIT_PARAMETERS_INCORRECT);
   }

   g_prefix = "KittVolBehavior_" + SanitizeId(InpUniqueId) + "_";
   g_renderingEnabled = (MQLInfoInteger(MQL_TESTER) == 0 ||
                         MQLInfoInteger(MQL_VISUAL_MODE) != 0);
   IndicatorSetString(INDICATOR_SHORTNAME, "Kitt Volume Behavior Bubbles [" + InpUniqueId + "]");
   IndicatorSetInteger(INDICATOR_DIGITS, _Digits);
   return(INIT_SUCCEEDED);
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
   if(rates_total < InpPeriodChartBars + 3)
      return(0);

   ArraySetAsSeries(time, false);
   ArraySetAsSeries(open, false);
   ArraySetAsSeries(high, false);
   ArraySetAsSeries(low, false);
   ArraySetAsSeries(close, false);

   if(prev_calculated == 0)
      ArrayInitialize(DummyBuffer, 0.0);

   // Events are attached only to completed chart candles. Rebuilding on each
   // lower-timeframe candle added work but could not add a visible event.
   const bool rebuild = (prev_calculated == 0 || rates_total != prev_calculated);

   if(rebuild)
   {
      const int oldCount = ArraySize(g_events);
      const datetime oldFirst = oldCount > 0 ? g_events[0].time : 0;
      const datetime oldLast  = oldCount > 0 ? g_events[oldCount - 1].time : 0;

      BuildEvents(rates_total, time, open, high, low, close);
      const int newCount = ArraySize(g_events);
      const datetime newFirst = newCount > 0 ? g_events[0].time : 0;
      const datetime newLast  = newCount > 0 ? g_events[newCount - 1].time : 0;

      if(prev_calculated == 0 || oldCount != newCount ||
         oldFirst != newFirst || oldLast != newLast)
         RenderEvents();
      else if(g_renderingEnabled && InpShowBubbles)
      {
         // Reproject the persistent canvas once as the chart advances.
         DrawBubbleCanvas();
         ChartRedraw(0);
      }
   }

   UpdateScorecard(false);
   return(rates_total);
}

//+------------------------------------------------------------------+
void BuildEvents(const int rates_total,
                 const datetime &time[],
                 const double &open[],
                 const double &high[],
                 const double &low[],
                 const double &close[])
{
   ArrayResize(g_events, 0);
   g_detectedTotal  = 0;
   g_usedRealVolume = false;
   g_usedTickVolume = false;

   const int lastClosed = rates_total - 2;
   int firstChart = 0;
   if(InpMaxBarsToCalculate > 0)
      firstChart = MathMax(0, lastClosed - InpMaxBarsToCalculate + 1);

   const int chartSeconds = PeriodSeconds(_Period);
   const int lowerSeconds = PeriodSeconds(g_lowerTf);
   const int samplesPerChart = MathMax(1, (int)MathRound((double)chartSeconds / lowerSeconds));
   const int windowSamples = MathMax(10, InpPeriodChartBars * samplesPerChart);

   datetime fromTime = time[firstChart] - (datetime)((long)(windowSamples + samplesPerChart + 2) * lowerSeconds);
   datetime toTime   = time[rates_total - 1] + (datetime)chartSeconds;

   MqlRates lowerRates[];
   ArraySetAsSeries(lowerRates, false);
   const int copied = CopyRates(_Symbol, g_lowerTf, fromTime, toTime, lowerRates);
   if(copied <= windowSamples)
      return;

   double prefix[];
   double prefixSq[];
   double lowerVolumes[];
   ArrayResize(prefix, copied + 1);
   ArrayResize(prefixSq, copied + 1);
   ArrayResize(lowerVolumes, copied);
   prefix[0] = 0.0;
   prefixSq[0] = 0.0;

   for(int i = 0; i < copied; ++i)
   {
      const double v = SelectedVolume(lowerRates[i]);
      lowerVolumes[i] = v;
      prefix[i + 1]   = prefix[i] + v;
      prefixSq[i + 1] = prefixSq[i] + v * v;
   }

   BubbleEvent detected[];
   ArrayResize(detected, InpMaxRenderedBubbles);
   int detectedCount = 0;

   for(int i = windowSamples; i < copied - 1 && !IsStopped(); ++i)
   {
      const double v = lowerVolumes[i];
      const double sum = prefix[i] - prefix[i - windowSamples];
      const double sumSq = prefixSq[i] - prefixSq[i - windowSamples];
      const double mean = sum / windowSamples;
      double variance = sumSq / windowSamples - mean * mean;
      if(variance < 0.0)
         variance = 0.0;
      const double deviation = MathSqrt(variance);
      if(deviation <= 0.0)
         continue;

      const double z = (v - mean) / deviation;
      const bool qualifies = InpPositiveSpikesOnly
                             ? (z >= InpZThreshold)
                             : (MathAbs(z) >= InpZThreshold);
      if(!qualifies)
         continue;

      const int shift = iBarShift(_Symbol, _Period, lowerRates[i].time, false);
      if(shift < 1)
         continue;
      const int parent = rates_total - 1 - shift;
      if(parent < firstChart || parent > lastClosed)
         continue;

      int direction = 0;
      if(lowerRates[i].close > lowerRates[i].open)
         direction = 1;
      else if(lowerRates[i].close < lowerRates[i].open)
         direction = -1;
      else if(i > 0)
         direction = (lowerRates[i].close >= lowerRates[i - 1].close) ? 1 : -1;
      else
         direction = (close[parent] >= open[parent]) ? 1 : -1;

      const double eventPrice = lowerRates[i].close;
      const double bodyLow  = MathMin(open[parent], close[parent]);
      const double bodyHigh = MathMax(open[parent], close[parent]);
      const double candleRange = high[parent] - low[parent];
      if(candleRange <= 0.0)
         continue;

      const double position = MathMax(0.0, MathMin(1.0,
                              (eventPrice - low[parent]) / candleRange));
      const double edgeDistance = MathMin(position, 1.0 - position);
      const bool insideBody = (eventPrice >= bodyLow && eventPrice <= bodyHigh);
      const int participant = (!insideBody && edgeDistance <= InpExtremeFraction)
                              ? KITT_RETAIL_CLASS
                              : KITT_SMART_CLASS;

      if(InpWhoToShow == KITT_SHOW_SMART_PROXY && participant != KITT_SMART_CLASS)
         continue;
      if(InpWhoToShow == KITT_SHOW_RETAIL_PROXY && participant != KITT_RETAIL_CLASS)
         continue;

      BubbleEvent event;
      event.time        = lowerRates[i].time;
      event.price       = eventPrice;
      event.z           = z;
      event.volume      = v;
      event.participant = participant;
      event.direction   = direction;

      detected[detectedCount % InpMaxRenderedBubbles] = event;
      ++detectedCount;
   }

   const int keep = MathMin(detectedCount, InpMaxRenderedBubbles);
   const int begin = detectedCount >= InpMaxRenderedBubbles
                     ? detectedCount % InpMaxRenderedBubbles
                     : 0;
   ArrayResize(g_events, keep, InpMaxRenderedBubbles);
   for(int k = 0; k < keep; ++k)
      g_events[k] = detected[(begin + k) % InpMaxRenderedBubbles];
   g_detectedTotal = detectedCount;
}

//+------------------------------------------------------------------+
double SelectedVolume(const MqlRates &bar)
{
   if(InpVolumeSource == KITT_VOLUME_REAL)
   {
      if(bar.real_volume > 0)
         g_usedRealVolume = true;
      return((double)bar.real_volume);
   }

   if(InpVolumeSource == KITT_VOLUME_TICK)
   {
      g_usedTickVolume = true;
      return((double)bar.tick_volume);
   }

   if(bar.real_volume > 0)
   {
      g_usedRealVolume = true;
      return((double)bar.real_volume);
   }

   g_usedTickVolume = true;
   return((double)bar.tick_volume);
}

//+------------------------------------------------------------------+
void RenderEvents()
{
   if(!g_renderingEnabled)
      return;

   SyncLevels();

   if(InpShowBubbles)
      DrawBubbleCanvas();

   if(InpShowScorecard)
      CreatePanelFrame();
   UpdateScorecard(true);
   ChartRedraw(0);
}

//+------------------------------------------------------------------+
void SyncLevels()
{
   if(!InpShowLevels)
   {
      ObjectsDeleteAll(0, g_prefix + "L_");
      ArrayResize(g_renderedLevelTimes, 0);
      return;
   }

   // Remove only levels that fell out of the capped event window.
   for(int old = 0; old < ArraySize(g_renderedLevelTimes); ++old)
   {
      bool stillPresent = false;
      for(int current = 0; current < ArraySize(g_events); ++current)
      {
         if(g_renderedLevelTimes[old] == g_events[current].time)
         {
            stillPresent = true;
            break;
         }
      }
      if(!stillPresent)
      {
         const string staleName = g_prefix + "L_" +
                                  StringFormat("%I64d", (long)g_renderedLevelTimes[old]);
         ObjectDelete(0, staleName);
      }
   }

   ArrayResize(g_renderedLevelTimes, ArraySize(g_events), InpMaxRenderedBubbles);
   for(int i = 0; i < ArraySize(g_events) && !IsStopped(); ++i)
   {
      CreateLevel(g_events[i]);
      g_renderedLevelTimes[i] = g_events[i].time;
   }
}

//+------------------------------------------------------------------+
bool EnsureBubbleCanvas()
{
   const int width  = (int)ChartGetInteger(0, CHART_WIDTH_IN_PIXELS, 0);
   const int height = (int)ChartGetInteger(0, CHART_HEIGHT_IN_PIXELS, 0);
   const string name = g_prefix + "BubbleCanvas";

   if(width < 2 || height < 2)
      return(false);

   if(g_canvasReady && width == g_canvasWidth && height == g_canvasHeight &&
      ObjectFind(0, name) >= 0)
      return(true);

   DestroyBubbleCanvas();
   if(!g_bubbleCanvas.CreateBitmapLabel(name, 0, 0, width, height,
                                        COLOR_FORMAT_ARGB_NORMALIZE))
   {
      Print("Kitt Volume Bubbles: canvas creation failed, error ", GetLastError());
      return(false);
   }

   g_canvasReady  = true;
   g_canvasWidth  = width;
   g_canvasHeight = height;
   ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, 0);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, 0);
   ObjectSetInteger(0, name, OBJPROP_BACK, InpObjectsInBackground);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_SELECTED, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
   return(true);
}

//+------------------------------------------------------------------+
void DestroyBubbleCanvas()
{
   if(g_canvasReady)
      g_bubbleCanvas.Destroy();

   g_canvasReady  = false;
   g_canvasWidth  = 0;
   g_canvasHeight = 0;
}

//+------------------------------------------------------------------+
void DrawBubbleCanvas()
{
   if(!InpShowBubbles || ArraySize(g_events) == 0 || !EnsureBubbleCanvas())
      return;

   g_bubbleCanvas.Erase(0x00000000);
   for(int i = 0; i < ArraySize(g_events) && !IsStopped(); ++i)
   {
      int x = 0;
      int y = 0;
      if(!ChartTimePriceToXY(0, 0, g_events[i].time, g_events[i].price, x, y))
         continue;

      const int diameter = BubbleSize(g_events[i].z);
      const int radius = diameter / 2 + 5;
      if(x < -radius || x >= g_canvasWidth + radius ||
         y < -radius || y >= g_canvasHeight + radius)
         continue;

      DrawGlossySphere(x, y, diameter, RawEventColor(g_events[i]));
   }
   g_bubbleCanvas.Update(false);
}

//+------------------------------------------------------------------+
void DrawGlossySphere(const int centerX,
                      const int centerY,
                      const int diameter,
                      const color baseColor)
{
   const double radius = MathMax(3.0, diameter * 0.5);
   const int bound = (int)MathCeil(radius + 5.0);
   const int baseR = ((int)baseColor) & 0xFF;
   const int baseG = (((int)baseColor) >> 8) & 0xFF;
   const int baseB = (((int)baseColor) >> 16) & 0xFF;
   const int opacity = (int)MathRound(255.0 * (100 - InpTransparency) / 100.0);

   // Soft drop shadow, slightly below and to the right of the sphere.
   for(int py = -bound; py <= bound; ++py)
   {
      const int canvasY = centerY + py;
      if(canvasY < 0 || canvasY >= g_canvasHeight)
         continue;

      for(int px = -bound; px <= bound; ++px)
      {
         const int canvasX = centerX + px;
         if(canvasX < 0 || canvasX >= g_canvasWidth)
            continue;

         const double sx = (px - 2.5) / (radius * 1.08);
         const double sy = (py - 3.5) / (radius * 0.92);
         const double shadowDistance = MathSqrt(sx * sx + sy * sy);
         if(shadowDistance <= 1.0)
         {
            const int shadowAlpha = (int)MathRound(60.0 * (1.0 - shadowDistance));
            g_bubbleCanvas.PixelSet(canvasX, canvasY,
                                    MakeArgb(shadowAlpha, 0, 0, 0));
         }
      }
   }

   // Lit sphere: radial depth, dark rim, upper-left specular highlight.
   for(int py = -bound; py <= bound; ++py)
   {
      const int canvasY = centerY + py;
      if(canvasY < 0 || canvasY >= g_canvasHeight)
         continue;

      for(int px = -bound; px <= bound; ++px)
      {
         const int canvasX = centerX + px;
         if(canvasX < 0 || canvasX >= g_canvasWidth)
            continue;

         const double nx = px / radius;
         const double ny = py / radius;
         const double distance2 = nx * nx + ny * ny;
         if(distance2 > 1.0)
            continue;

         const double nz = MathSqrt(MathMax(0.0, 1.0 - distance2));
         const double lightDot = MathMax(0.0,
                                 nx * -0.48 + ny * -0.58 + nz * 0.66);
         const double rim = MathPow(nz, 0.42);
         double shade = 0.10 + 0.68 * lightDot + 0.30 * rim;

         const double hx = nx + 0.36;
         const double hy = ny + 0.40;
         const double specular = MathExp(-(hx * hx + hy * hy) / 0.030);
         const double broadGlow = MathExp(-(hx * hx + hy * hy) / 0.22);

         int red   = ClampByte((int)MathRound(baseR * shade + 225.0 * specular + 38.0 * broadGlow));
         int green = ClampByte((int)MathRound(baseG * shade + 235.0 * specular + 42.0 * broadGlow));
         int blue  = ClampByte((int)MathRound(baseB * shade + 255.0 * specular + 55.0 * broadGlow));

         double edgeAlpha = 1.0;
         const double distance = MathSqrt(distance2);
         if(distance > 0.92)
            edgeAlpha = MathMax(0.0, (1.0 - distance) / 0.08);
         if(InpBubbleMode == KITT_BUBBLE_OUTLINE && distance < 0.68)
            edgeAlpha *= 0.18;

         const int alpha = ClampByte((int)MathRound(opacity * edgeAlpha));
         g_bubbleCanvas.PixelSet(canvasX, canvasY,
                                 MakeArgb(alpha, red, green, blue));
      }
   }
}

//+------------------------------------------------------------------+
uint MakeArgb(const int alpha, const int red, const int green, const int blue)
{
   return(((uint)ClampByte(alpha) << 24) |
          ((uint)ClampByte(red)   << 16) |
          ((uint)ClampByte(green) << 8)  |
          (uint)ClampByte(blue));
}

//+------------------------------------------------------------------+
int ClampByte(const int value)
{
   return(MathMax(0, MathMin(255, value)));
}

//+------------------------------------------------------------------+
color RawEventColor(const BubbleEvent &event)
{
   if(event.participant == KITT_SMART_CLASS)
      return(event.direction > 0 ? InpSmartBullColor : InpSmartBearColor);

   return(event.direction > 0 ? InpRetailBullColor : InpRetailBearColor);
}

//+------------------------------------------------------------------+
void CreateLevel(const BubbleEvent &event)
{
   const int lowerSeconds = PeriodSeconds(g_lowerTf);
   const string name = g_prefix + "L_" + StringFormat("%I64d", (long)event.time);
   if(ObjectFind(0, name) < 0)
   {
      if(!ObjectCreate(0, name, OBJ_TREND, 0,
                       event.time, event.price,
                       event.time + (datetime)lowerSeconds, event.price))
         return;
   }
   else
   {
      ObjectMove(0, name, 0, event.time, event.price);
      ObjectMove(0, name, 1, event.time + (datetime)lowerSeconds, event.price);
   }

   ObjectSetInteger(0, name, OBJPROP_RAY_RIGHT, true);
   ObjectSetInteger(0, name, OBJPROP_STYLE, STYLE_DOT);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, 1);
   ObjectSetInteger(0, name, OBJPROP_COLOR, DisplayColor(event));
   SetCommonObjectProperties(name);
}

//+------------------------------------------------------------------+
void SetCommonObjectProperties(const string name)
{
   ObjectSetInteger(0, name, OBJPROP_BACK, InpObjectsInBackground);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_SELECTED, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
}

//+------------------------------------------------------------------+
int BubbleSize(const double z)
{
   const double severity = MathMin(MathAbs(z), InpZSizeCap);
   const double t = MathMax(0.0, MathMin(1.0,
                    (severity - InpZThreshold) / (InpZSizeCap - InpZThreshold)));
   return((int)MathRound(InpMinimumBubbleSize +
                         t * (InpMaximumBubbleSize - InpMinimumBubbleSize)));
}

//+------------------------------------------------------------------+
color DisplayColor(const BubbleEvent &event)
{
   const color base = RawEventColor(event);
   const color background = (color)ChartGetInteger(0, CHART_COLOR_BACKGROUND, 0);
   return(BlendColor(base, background, 100 - InpTransparency));
}

//+------------------------------------------------------------------+
color BlendColor(const color foreground, const color background, const int opacityPercent)
{
   const double a = MathMax(0.0, MathMin(1.0, opacityPercent / 100.0));
   const int fr = ((int)foreground) & 0xFF;
   const int fg = (((int)foreground) >> 8) & 0xFF;
   const int fb = (((int)foreground) >> 16) & 0xFF;
   const int br = ((int)background) & 0xFF;
   const int bg = (((int)background) >> 8) & 0xFF;
   const int bb = (((int)background) >> 16) & 0xFF;

   const int r = (int)MathRound(fr * a + br * (1.0 - a));
   const int g = (int)MathRound(fg * a + bg * (1.0 - a));
   const int b = (int)MathRound(fb * a + bb * (1.0 - a));
   return((color)(r | (g << 8) | (b << 16)));
}

//+------------------------------------------------------------------+
void CreatePanelFrame()
{
   const string frame = g_prefix + "Panel";
   if(ObjectFind(0, frame) < 0)
      ObjectCreate(0, frame, OBJ_RECTANGLE_LABEL, 0, 0, 0);

   ObjectSetInteger(0, frame, OBJPROP_CORNER, InpPanelCorner);
   ObjectSetInteger(0, frame, OBJPROP_XDISTANCE, InpPanelX);
   ObjectSetInteger(0, frame, OBJPROP_YDISTANCE, InpPanelY);
   ObjectSetInteger(0, frame, OBJPROP_XSIZE, 284);
   ObjectSetInteger(0, frame, OBJPROP_YSIZE, 91);
   ObjectSetInteger(0, frame, OBJPROP_BGCOLOR, InpPanelBackground);
   ObjectSetInteger(0, frame, OBJPROP_BORDER_COLOR, clrDimGray);
   ObjectSetInteger(0, frame, OBJPROP_BACK, false);
   ObjectSetInteger(0, frame, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, frame, OBJPROP_HIDDEN, true);

   CreatePanelLabel("Title", 9, 7,  "VOLUME BEHAVIOR PROXY", 9, InpPanelTextColor);
   CreatePanelLabel("Head",  9, 27, "Class             Profit*       Loss*", 8, clrSilver);
   CreatePanelLabel("Retail",9, 45, "Retail", 9, InpPanelTextColor);
   CreatePanelLabel("Smart", 9, 63, "Smart",  9, InpPanelTextColor);
   CreatePanelLabel("Status",137, 7, "", 7, clrSilver);
}

//+------------------------------------------------------------------+
void CreatePanelLabel(const string suffix,
                      const int x,
                      const int y,
                      const string text,
                      const int fontSize,
                      const color textColor)
{
   const string name = g_prefix + "Panel_" + suffix;
   if(ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0);

   ObjectSetInteger(0, name, OBJPROP_CORNER, InpPanelCorner);
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, InpPanelX + x);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, InpPanelY + y);
   ObjectSetInteger(0, name, OBJPROP_ANCHOR, AnchorForCorner());
   ObjectSetString(0, name, OBJPROP_TEXT, text);
   ObjectSetString(0, name, OBJPROP_FONT, "Consolas");
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE, fontSize);
   ObjectSetInteger(0, name, OBJPROP_COLOR, textColor);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
}

//+------------------------------------------------------------------+
ENUM_ANCHOR_POINT AnchorForCorner()
{
   if(InpPanelCorner == CORNER_RIGHT_UPPER)
      return(ANCHOR_RIGHT_UPPER);
   if(InpPanelCorner == CORNER_LEFT_LOWER)
      return(ANCHOR_LEFT_LOWER);
   if(InpPanelCorner == CORNER_RIGHT_LOWER)
      return(ANCHOR_RIGHT_LOWER);
   return(ANCHOR_LEFT_UPPER);
}

//+------------------------------------------------------------------+
void UpdateScorecard(const bool force)
{
   if(!g_renderingEnabled || !InpShowScorecard)
      return;

   const uint now = GetTickCount();
   if(!force && InpScorecardRefreshMs > 0 &&
      now - g_lastScorecardMs < (uint)InpScorecardRefreshMs)
      return;
   g_lastScorecardMs = now;

   if(ObjectFind(0, g_prefix + "Panel") < 0)
      CreatePanelFrame();

   double retailProfit = 0.0;
   double retailLoss   = 0.0;
   double smartProfit  = 0.0;
   double smartLoss    = 0.0;

   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   if(bid <= 0.0)
      bid = iClose(_Symbol, _Period, 0);
   if(ask <= 0.0)
      ask = bid;

   for(int i = 0; i < ArraySize(g_events); ++i)
   {
      const double exitPrice = (g_events[i].direction > 0) ? bid : ask;
      const double points = (g_events[i].direction > 0)
                            ? (exitPrice - g_events[i].price) / _Point
                            : (g_events[i].price - exitPrice) / _Point;
      const double weighted = points * MathAbs(g_events[i].z);

      if(g_events[i].participant == KITT_RETAIL_CLASS)
      {
         if(weighted >= 0.0)
            retailProfit += weighted;
         else
            retailLoss += -weighted;
      }
      else
      {
         if(weighted >= 0.0)
            smartProfit += weighted;
         else
            smartLoss += -weighted;
      }
   }

   SetPanelText("Retail", StringFormat("Retail        %9s   %9s",
                CompactNumber(retailProfit), CompactNumber(retailLoss)));
   SetPanelText("Smart", StringFormat("Smart         %9s   %9s",
                CompactNumber(smartProfit), CompactNumber(smartLoss)));
   SetPanelText("Status", TimeframeToText(g_lowerTf) + "  " + VolumeModeText());
   ObjectSetInteger(0, g_prefix + "Panel_Retail", OBJPROP_COLOR,
                    retailProfit >= retailLoss ? clrLimeGreen : clrTomato);
   ObjectSetInteger(0, g_prefix + "Panel_Smart", OBJPROP_COLOR,
                    smartProfit >= smartLoss ? clrLimeGreen : clrTomato);
}

//+------------------------------------------------------------------+
void SetPanelText(const string suffix, const string value)
{
   ObjectSetString(0, g_prefix + "Panel_" + suffix, OBJPROP_TEXT, value);
}

//+------------------------------------------------------------------+
string CompactNumber(const double value)
{
   if(value >= 1000000.0)
      return(DoubleToString(value / 1000000.0, 2) + "M");
   if(value >= 1000.0)
      return(DoubleToString(value / 1000.0, 2) + "K");
   return(DoubleToString(value, 0));
}

//+------------------------------------------------------------------+
string VolumeModeText()
{
   string source = "NO VOL";
   if(g_usedRealVolume && g_usedTickVolume)
      source = "REAL/TICK";
   else if(g_usedRealVolume)
      source = "REAL VOL";
   else if(g_usedTickVolume)
      source = "TICK VOL";

   return(source + "  N=" + IntegerToString(ArraySize(g_events)));
}

//+------------------------------------------------------------------+
string TimeframeToText(const ENUM_TIMEFRAMES timeframe)
{
   string value = EnumToString(timeframe);
   StringReplace(value, "PERIOD_", "");
   return(value);
}

//+------------------------------------------------------------------+
string SanitizeId(string value)
{
   StringReplace(value, " ", "_");
   StringReplace(value, ".", "_");
   StringReplace(value, "-", "_");
   return(value);
}

//+------------------------------------------------------------------+
void OnChartEvent(const int id,
                  const long &lparam,
                  const double &dparam,
                  const string &sparam)
{
   if(id == CHARTEVENT_CHART_CHANGE && InpShowBubbles)
   {
      if(!g_renderingEnabled)
         return;
      DrawBubbleCanvas();
   }
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   DestroyBubbleCanvas();
   ObjectsDeleteAll(0, g_prefix);
   ChartRedraw(0);
}
//+------------------------------------------------------------------+
