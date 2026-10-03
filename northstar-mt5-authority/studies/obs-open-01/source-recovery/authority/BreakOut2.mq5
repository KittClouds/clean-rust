//+------------------------------------------------------------------+
//|                                                     Breakout.mq5 |
//|                        Copyright 2018, MetaQuotes Software Corp. |
//|                                                 https://mql5.com |
//+------------------------------------------------------------------+
#property copyright "Copyright 2018, MetaQuotes Software Corp."
#property link      "https://mql5.com"
#property version   "1.00"
#property description "Breakout zones"
#property indicator_chart_window
#property indicator_buffers 4
#property indicator_plots   4
//--- plot Upper Period
#property indicator_label1  "Upper period"
#property indicator_type1   DRAW_LINE
#property indicator_color1  clrRed
#property indicator_style1  STYLE_SOLID
#property indicator_width1  2
//--- plot Lower Period
#property indicator_label2  "Lower period"
#property indicator_type2   DRAW_LINE
#property indicator_color2  clrRed
#property indicator_style2  STYLE_SOLID
#property indicator_width2  2
//--- plot Upper Area
#property indicator_label3  "Upper area"
#property indicator_type3   DRAW_LINE
#property indicator_color3  clrFuchsia
#property indicator_style3  STYLE_DOT
#property indicator_width3  1
//--- plot Lower Area
#property indicator_label4  "Lower area"
#property indicator_type4   DRAW_LINE
#property indicator_color4  clrFuchsia
#property indicator_style4  STYLE_DOT
#property indicator_width4  1
//--- input parameters
input uint     InpHourBegin   =  0;    // "Period" Hour begin
input uint     InpMinBegin    =  0;    // "Period" Minutes begin
input uint     InpHourEnd     =  5;    // "Period" Hour end
input uint     InpMinEnd      =  0;    // "Period" Minutes end
input uint     InpHourEndArea =  23;   // "Area" Hour end
input uint     InpMinEndArea  =  0;    // "Area" Minutes end
//--- indicator buffers
double         BufferUpperPeriod[];
double         BufferLowerPeriod[];
double         BufferUpperArea[];
double         BufferLowerArea[];
//--- global variables
int            hour_begin;
int            min_begin;
int            hour_end;
int            min_end;
int            hour_box_end;
int            min_box_end;
long           period_begin_min;
long           period_end_min;
long           box_end_mn;
//+------------------------------------------------------------------+
//| Custom indicator initialization function                         |
//+------------------------------------------------------------------+
int OnInit()
  {
//--- set global variables
   hour_begin=int(InpHourBegin>23 ? 23 : InpHourBegin);
   min_begin=int(InpMinBegin>59 ? 59 : InpMinBegin);
   hour_end=int(InpHourEnd>23 ? 23 : InpHourEnd);
   min_end=int(InpMinEnd>59 ? 59 : InpMinEnd);
   hour_box_end=int(InpHourEndArea>23 ? 23 : InpHourEndArea<(uint)hour_end ? hour_end : InpHourEndArea);
   min_box_end=int(InpMinEndArea>59 ? 59 : InpMinEndArea);
//---
   period_begin_min=60*hour_begin+min_begin;
   period_end_min=60*hour_end+min_end;
   box_end_mn=60*hour_box_end+min_box_end;
//--- indicator buffers mapping
   SetIndexBuffer(0,BufferUpperPeriod,INDICATOR_DATA);
   SetIndexBuffer(1,BufferLowerPeriod,INDICATOR_DATA);
   SetIndexBuffer(2,BufferUpperArea,INDICATOR_DATA);
   SetIndexBuffer(3,BufferLowerArea,INDICATOR_DATA);
//--- setting indicator parameters
   IndicatorSetString(INDICATOR_SHORTNAME,"Breakout");
   IndicatorSetInteger(INDICATOR_DIGITS,Digits());
//--- setting buffer arrays as timeseries
   ArraySetAsSeries(BufferUpperPeriod,true);
   ArraySetAsSeries(BufferLowerPeriod,true);
   ArraySetAsSeries(BufferUpperArea,true);
   ArraySetAsSeries(BufferLowerArea,true);
//---
   return(INIT_SUCCEEDED);
  }
//+------------------------------------------------------------------+
//| Custom indicator iteration function                              |
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
//--- Check for the minimum number of bars for calculation
   if(rates_total<4) return 0;
//--- Set buffer arrays as timeseries
   ArraySetAsSeries(high,true);
   ArraySetAsSeries(low,true);
   ArraySetAsSeries(time,true);
//--- Check and calculate the number of bars to be calculated
   int limit=rates_total-prev_calculated;
   if(limit>1)
     {
      limit=rates_total-1;
      ArrayInitialize(BufferUpperPeriod,EMPTY_VALUE);
      ArrayInitialize(BufferLowerPeriod,EMPTY_VALUE);
      ArrayInitialize(BufferUpperArea,EMPTY_VALUE);
      ArrayInitialize(BufferLowerArea,EMPTY_VALUE);
     }
//--- Data preparation
   int begin_bar,end_bar;
   double min_price,max_price;
//--- Indicator calculation
   for(int i=limit; i>=0 && !IsStopped(); i--)
     {
      int cur_min=TimeHour(time[i])*60+TimeMinute(time[i]);
      if((period_end_min>period_begin_min && cur_min>=period_begin_min && cur_min<=period_end_min) ||
         (period_end_min<period_begin_min && (cur_min>=period_begin_min || cur_min<=period_end_min)))
        {
         begin_bar=FindBar(InpHourBegin,InpMinBegin,time[i]);
         if(begin_bar==WRONG_VALUE) continue;
         int hb=Highest(begin_bar-i+1,i);
         int lb=Lowest(begin_bar-i+1,i);
         if(hb==WRONG_VALUE || lb==WRONG_VALUE) continue;
         max_price=high[hb];
         min_price=low[lb];
         for(int j=begin_bar; j>=i; j--)
           {
            BufferUpperPeriod[j]=max_price;
            BufferLowerPeriod[j]=min_price;
           }
        }
      else
        {
         BufferUpperPeriod[i]=EMPTY_VALUE;
         BufferLowerPeriod[i]=EMPTY_VALUE;
        }
      if((box_end_mn>period_end_min && cur_min>=period_end_min && cur_min<=box_end_mn) ||
         (box_end_mn<period_end_min && (cur_min>=period_end_min || cur_min<=box_end_mn)))
        {
         begin_bar=FindBar(InpHourBegin,InpMinBegin,time[i]);
         end_bar=FindBar(InpHourEnd,InpMinEnd,time[i]);
         if(begin_bar==WRONG_VALUE || end_bar==WRONG_VALUE) continue;
         int hb=Highest(begin_bar-end_bar+1,end_bar);
         int lb=Lowest(begin_bar-end_bar+1,end_bar);
         if(hb==WRONG_VALUE || lb==WRONG_VALUE) continue;
         max_price=high[hb];
         min_price=low[lb];
         for(int j=end_bar; j>=i; j--)
           {
            BufferUpperArea[j]=max_price;
            BufferLowerArea[j]=min_price;
           }
        }
      else
        {
         BufferUpperArea[i]=EMPTY_VALUE;
         BufferLowerArea[i]=EMPTY_VALUE;
        }
     }

//--- return value of prev_calculated for next call
   return(rates_total);
  }
//+------------------------------------------------------------------+
//| Returns the hour of the specified time                           |
//+------------------------------------------------------------------+
int TimeHour(const datetime time)
  {
   MqlDateTime tm;
   TimeToStruct(time,tm);
   return tm.hour;
  }
//+------------------------------------------------------------------+
//| Returns the minute of the specified time                         |
//+------------------------------------------------------------------+
int TimeMinute(const datetime time)
  {
   MqlDateTime tm;
   TimeToStruct(time,tm);
   return tm.min;
  }
//+------------------------------------------------------------------+
//|                                                                  |
//+------------------------------------------------------------------+
int FindBar(int hour,int minutes,datetime time)
  {
   MqlDateTime tm;
   TimeToStruct(time,tm);
   tm.hour=hour;
   tm.min=minutes;
   datetime t=StructToTime(tm);
   if(t>time)
      t-=86400;
   return BarShift(Symbol(),PERIOD_CURRENT,t);
  }
//+------------------------------------------------------------------+
//| Returns the bar shift by time                                    |
//| https://www.mql5.com/en/code/1864                                |
//+------------------------------------------------------------------+
int BarShift(const string symbol_name,const ENUM_TIMEFRAMES timeframe,const datetime time,bool exact=false)
  {
   datetime last_bar;
   if(!SeriesInfoInteger(symbol_name,timeframe,SERIES_LASTBAR_DATE,last_bar))
     {
      datetime array[1];
      if(CopyTime(symbol_name,timeframe,0,1,array)==1)
         last_bar=array[0];
      else
         return WRONG_VALUE;
     }
   if(time>last_bar)
      return(0);
   int shift=Bars(symbol_name,timeframe,time,last_bar);
   datetime array[1];
   if(CopyTime(symbol_name,timeframe,time,1,array)==1)
      return(array[0]==time ? shift-1 : exact && time>array[0]+PeriodSeconds(timeframe) ? WRONG_VALUE : shift);
   return WRONG_VALUE;
  }
//+------------------------------------------------------------------+
//| Returns the index of the highest value in the High timeseries    |
//+------------------------------------------------------------------+
int Highest(const int count,const int start)
  {
   double array[];
   ArraySetAsSeries(array,true);
   if(CopyHigh(Symbol(),PERIOD_CURRENT,start,count,array)==count)
      return ArrayMaximum(array)+start;
   return WRONG_VALUE;
  }
//+------------------------------------------------------------------+
//| Returns the index of the lowest value in the Low timeseries      |
//+------------------------------------------------------------------+
int Lowest(const int count,const int start)
  {
   double array[];
   ArraySetAsSeries(array,true);
   if(CopyLow(Symbol(),PERIOD_CURRENT,start,count,array)==count)
      return ArrayMinimum(array)+start;
   return WRONG_VALUE;
  }
//+------------------------------------------------------------------+
