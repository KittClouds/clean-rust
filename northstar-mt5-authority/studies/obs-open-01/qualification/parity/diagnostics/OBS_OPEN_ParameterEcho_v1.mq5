//+------------------------------------------------------------------+
//| OBS_OPEN_ParameterEcho_v1.mq5                                   |
//| Diagnostic-only mirror of the frozen observer input ABI.        |
//+------------------------------------------------------------------+
#property strict
#property indicator_chart_window
#property indicator_buffers 1
#property indicator_plots 1
#property indicator_type1 DRAW_NONE

input group "Opening Range Clock"
input int InpStartHour=9;
input int InpStartMinute=30;
input int InpRangeMinutes=5;
input int InpAreaEndHour=16;
input int InpAreaEndMinute=0;
input int InpHistoryDays=20;

input group "Coverage Contract"
input bool InpRequireEveryM1Bar=true;
input bool InpRequireChartContinuity=true;

input group "Original-Style Drawing"
input bool InpShowRangeArea=true;
input bool InpShowPostRangeArea=true;
input bool InpShowMidline=false;
input bool InpShowLabels=true;
input color InpRangeColor=clrRed;
input color InpExtensionColor=clrViolet;
input color InpMidColor=clrMediumPurple;
input int InpRangeAlpha=32;
input int InpExtensionAlpha=12;
input int InpRailWidth=1;
input ENUM_LINE_STYLE InpRailStyle=STYLE_SOLID;
input string InpUniqueId="01";

double EchoBuffer[];

int OnInit()
  {
   SetIndexBuffer(0,EchoBuffer,INDICATOR_DATA);
   PrintFormat("OBS_OPEN_ABI_ECHO id=%s start=%d:%d range=%d end=%d:%d history=%d "
               "m1=%d continuity=%d show=%d,%d,%d,%d colors=%d,%d,%d "
               "alpha=%d,%d width=%d style=%d",
               InpUniqueId,InpStartHour,InpStartMinute,InpRangeMinutes,
               InpAreaEndHour,InpAreaEndMinute,InpHistoryDays,
               (int)InpRequireEveryM1Bar,(int)InpRequireChartContinuity,
               (int)InpShowRangeArea,(int)InpShowPostRangeArea,
               (int)InpShowMidline,(int)InpShowLabels,
               (int)InpRangeColor,(int)InpExtensionColor,(int)InpMidColor,
               InpRangeAlpha,InpExtensionAlpha,InpRailWidth,(int)InpRailStyle);
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
   if(rates_total>0)
      EchoBuffer[rates_total-1]=0.0;
   return rates_total;
  }
