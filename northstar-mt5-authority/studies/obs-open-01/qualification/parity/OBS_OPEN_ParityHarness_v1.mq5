//+------------------------------------------------------------------+
//| OBS_OPEN_ParityHarness_v1.mq5                                   |
//| Indicator-mode black-box R01-R30 tester harness.                |
//+------------------------------------------------------------------+
#property strict
#property indicator_chart_window
#property indicator_buffers 1
#property indicator_plots 1
#property indicator_type1 DRAW_NONE
#property tester_indicator "OpeningRangeGrammar_v1_02_FullState.ex5"

input string InpInvocationTag = "run1";
input int InpStartHour = 16;
input int InpStartMinute = 30;
input int InpAreaEndHour = 23;
input int InpAreaEndMinute = 0;
input int InpHistoryDays = 3;

#define RANGE_COUNT 30
#define BUFFER_COUNT 17
const string SCHEMA = "OBS_OPEN_PARITY_BLACKBOX_V1";

double g_dummy[];
int g_handles[RANGE_COUNT];
int g_data=INVALID_HANDLE;
int g_receipt=INVALID_HANDLE;
datetime g_last_closed=0;
long g_rows=0;
long g_copy_failures=0;

string LongText(const long value) { return StringFormat("%I64d",value); }

string ValueText(const double value)
  {
   if(value==EMPTY_VALUE || !MathIsValidNumber(value)) return "NOT_AVAILABLE";
   return DoubleToString(value,12);
  }
int CreateObserver(const int range_minutes)
  {
   return iCustom(_Symbol,PERIOD_M5,"OpeningRangeGrammar_v1_02_FullState",
                  InpStartHour,InpStartMinute,range_minutes,
                  InpAreaEndHour,InpAreaEndMinute,InpHistoryDays,
                  true,true,false,false,false,false,
                  clrRed,clrViolet,clrMediumPurple,32,12,1,STYLE_SOLID,
                  "OBS_OPEN_PARITY_"+IntegerToString(range_minutes));
  }

int OnInit()
  {
   SetIndexBuffer(0,g_dummy,INDICATOR_DATA);
   PlotIndexSetString(0,PLOT_LABEL,"qualification-only");
   const string stem="OBS_OPEN_01_parity_"+InpInvocationTag;
   g_data=FileOpen(stem+"_buffers.tsv",FILE_COMMON|FILE_WRITE|FILE_CSV|FILE_ANSI,'\t');
   g_receipt=FileOpen(stem+"_receipt.tsv",FILE_COMMON|FILE_WRITE|FILE_CSV|FILE_ANSI,'\t');
   if(g_data==INVALID_HANDLE || g_receipt==INVALID_HANDLE) return INIT_FAILED;
   FileWrite(g_data,"schema","invocation","range_minutes","bar_open_epoch","bar_open_time",
             "range_high","range_low","range_mid","range_width","lifecycle","range_open",
             "range_closed","area_active","interaction_eligible","location","grammar_event",
             "outside_run","first_outside_side","above_excursions","below_excursions",
             "failed_above","failed_below");
   FileWrite(g_receipt,"schema","invocation","symbol","period","start_hour","start_minute",
             "area_end_hour","area_end_minute","handles_ok","rows","copy_failures","deinit_reason");
   for(int i=0;i<RANGE_COUNT;i++)
     {
      g_handles[i]=CreateObserver(i+1);
      if(g_handles[i]==INVALID_HANDLE) return INIT_FAILED;
     }
   return INIT_SUCCEEDED;
  }

void EmitClosedBar(const datetime bar_open)
  {
   const int shift=iBarShift(_Symbol,PERIOD_M5,bar_open,true);
   if(shift<0) { g_copy_failures+=RANGE_COUNT; return; }
   for(int r=0;r<RANGE_COUNT;r++)
     {
      string values[BUFFER_COUNT];
      for(int b=0;b<BUFFER_COUNT;b++)
        {
         double cell[1];
         ResetLastError();
         if(CopyBuffer(g_handles[r],b,shift,1,cell)!=1)
           {
            values[b]="COPY_ERROR_"+IntegerToString(GetLastError());
            g_copy_failures++;
           }
         else values[b]=ValueText(cell[0]);
        }
      FileWrite(g_data,SCHEMA,InpInvocationTag,IntegerToString(r+1),LongText((long)bar_open),
                TimeToString(bar_open,TIME_DATE|TIME_SECONDS),values[0],values[1],values[2],
                values[3],values[4],values[5],values[6],values[7],values[8],values[9],
                values[10],values[11],values[12],values[13],values[14],values[15],values[16]);
      g_rows++;
     }
  }

int OnCalculate(const int rates_total,const int prev_calculated,const datetime &time[],
                const double &open[],const double &high[],const double &low[],const double &close[],
                const long &tick_volume[],const long &volume[],const int &spread[])
  {
   ArraySetAsSeries(time,true);
   if(rates_total<2) return 0;
   const datetime latest=time[1];
   if(latest>0 && latest!=g_last_closed)
     {
      EmitClosedBar(latest);
      g_last_closed=latest;
     }
   return rates_total;
  }

void OnDeinit(const int reason)
  {
   for(int i=0;i<RANGE_COUNT;i++) if(g_handles[i]!=INVALID_HANDLE) IndicatorRelease(g_handles[i]);
   if(g_receipt!=INVALID_HANDLE)
     {
      FileWrite(g_receipt,SCHEMA,InpInvocationTag,_Symbol,EnumToString(PERIOD_M5),
                IntegerToString(InpStartHour),IntegerToString(InpStartMinute),
                IntegerToString(InpAreaEndHour),IntegerToString(InpAreaEndMinute),
                IntegerToString(RANGE_COUNT),LongText(g_rows),LongText(g_copy_failures),IntegerToString(reason));
      FileFlush(g_receipt); FileClose(g_receipt);
     }
   if(g_data!=INVALID_HANDLE) { FileFlush(g_data); FileClose(g_data); }
  }
