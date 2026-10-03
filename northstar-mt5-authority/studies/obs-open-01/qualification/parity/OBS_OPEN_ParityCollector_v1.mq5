//+------------------------------------------------------------------+
//| OBS_OPEN_ParityCollector_v1.mq5                                 |
//| Black-box R01-R30 qualification collector for the frozen ORG.   |
//+------------------------------------------------------------------+
#property strict
#property tester_indicator "OpeningRangeGrammar_v1_02_FullState.ex5"

input string InpInvocationTag = "run1";
input int    InpStartHour = 16;
input int    InpStartMinute = 30;
input int    InpAreaEndHour = 23;
input int    InpAreaEndMinute = 0;
input int    InpHistoryDays = 3;
input datetime InpDeterministicCutoff = D'2026.08.14 00:00:00';

#define RANGE_COUNT 30
#define BUFFER_COUNT 17
const string SCHEMA = "OBS_OPEN_PARITY_BLACKBOX_V1";

int g_handles[RANGE_COUNT];
int g_handles_ok = 0;
bool g_observers_ready = false;
int g_data = INVALID_HANDLE;
int g_receipt = INVALID_HANDLE;
datetime g_last_closed = 0;
long g_rows = 0;
long g_copy_failures = 0;
long g_readiness_deferrals = 0;
long g_finalized_bar_rows = 0;

string LongText(const long value)
  {
   return StringFormat("%I64d",value);
  }

string ValueText(const double value)
  {
   if(value==EMPTY_VALUE || !MathIsValidNumber(value))
      return "NOT_AVAILABLE";
   return DoubleToString(value,12);
  }

bool OpenOutputs()
  {
   const string stem="OBS_OPEN_01_parity_"+InpInvocationTag;
   g_data=FileOpen(stem+"_buffers.tsv",FILE_COMMON|FILE_WRITE|FILE_CSV|FILE_ANSI,'\t');
   g_receipt=FileOpen(stem+"_receipt.tsv",FILE_COMMON|FILE_WRITE|FILE_CSV|FILE_ANSI,'\t');
   if(g_data==INVALID_HANDLE || g_receipt==INVALID_HANDLE)
      return false;

   FileWrite(g_data,
             "schema","invocation","range_minutes","bar_open_epoch","bar_open_time",
             "range_high","range_low","range_mid","range_width","lifecycle",
             "range_open","range_closed","area_active","interaction_eligible",
             "location","grammar_event","outside_run","first_outside_side",
             "above_excursions","below_excursions","failed_above","failed_below");
   FileWrite(g_receipt,"schema","invocation","symbol","period","start_hour","start_minute",
             "area_end_hour","area_end_minute","handles_ok","rows","copy_failures",
             "readiness_deferrals","finalized_bar_rows","deinit_reason");
   return true;
  }

bool HandlesSynchronized()
  {
   // Subordinate custom indicators are evaluated lazily in the tester. A
   // shift-1 CopyBuffer probe both requests calculation and proves the exact
   // causal cell needed by EmitClosedBar is available. No row is emitted until
   // every observer passes the probe.
   for(int i=0;i<RANGE_COUNT;i++)
     {
      double probe[1];
      ResetLastError();
      if(CopyBuffer(g_handles[i],0,1,1,probe)!=1)
         return false;
     }

   return true;
  }

bool PrepareObservers()
  {
   for(int range_index=0;range_index<RANGE_COUNT;range_index++)
     {
      // MT5's runtime ABI includes each `input group` heading as a string
      // parameter. The three headings are therefore supplied explicitly and
      // in source order before their corresponding visible inputs.
      g_handles[range_index]=iCustom(_Symbol,PERIOD_M5,
                                     "OpeningRangeGrammar_v1_02_FullState",
                                     "Opening Range Clock",
                                     InpStartHour,InpStartMinute,range_index+1,
                                     InpAreaEndHour,InpAreaEndMinute,InpHistoryDays,
                                     "Coverage Contract",true,true,
                                     "Original-Style Drawing",
                                     false,false,false,false,
                                     clrRed,clrViolet,clrMediumPurple,
                                     32,12,1,STYLE_SOLID,
                                     "OBS_OPEN_PARITY_"+IntegerToString(range_index+1));
      if(g_handles[range_index]==INVALID_HANDLE)
        {
         Print("OBS_OPEN_PARITY handle failure R",range_index+1,
               " error=",GetLastError());
         for(int prior=0;prior<range_index;prior++)
           {
            IndicatorRelease(g_handles[prior]);
            g_handles[prior]=INVALID_HANDLE;
           }
         g_handles_ok=0;
         return false;
        }
      g_handles_ok++;
     }
   g_observers_ready=true;
   return true;
  }

int OnInit()
  {
   if(!OpenOutputs())
      return INIT_FAILED;
   return INIT_SUCCEEDED;
  }

void EmitClosedBar(const datetime bar_open)
  {
   const int shift=iBarShift(_Symbol,PERIOD_M5,bar_open,true);
   if(shift<0)
     {
      g_copy_failures+=RANGE_COUNT;
      return;
     }

   for(int range_index=0;range_index<RANGE_COUNT;range_index++)
     {
      string values[BUFFER_COUNT];
      bool complete=true;
      for(int buffer=0;buffer<BUFFER_COUNT;buffer++)
        {
         double cell[1];
         ResetLastError();
         if(CopyBuffer(g_handles[range_index],buffer,shift,1,cell)!=1)
           {
            values[buffer]="COPY_ERROR_"+IntegerToString(GetLastError());
            complete=false;
            g_copy_failures++;
           }
         else
            values[buffer]=ValueText(cell[0]);
        }

      FileWrite(g_data,
                SCHEMA,InpInvocationTag,IntegerToString(range_index+1),
                LongText((long)bar_open),TimeToString(bar_open,TIME_DATE|TIME_SECONDS),
                values[0],values[1],values[2],values[3],values[4],values[5],
                values[6],values[7],values[8],values[9],values[10],values[11],
                values[12],values[13],values[14],values[15],values[16]);
      g_rows++;
      if(!complete)
         Print("OBS_OPEN_PARITY incomplete row R",range_index+1," at ",bar_open);
     }
  }

void OnTick()
  {
   if(!g_observers_ready)
     {
      if(!PrepareObservers())
        {
         g_readiness_deferrals++;
         return;
        }
     }

   const datetime latest=iTime(_Symbol,PERIOD_M5,1);
   if(latest<=0 || latest==g_last_closed)
      return;
   if(!HandlesSynchronized())
     {
      g_readiness_deferrals++;
      return;
     }
   EmitClosedBar(latest);
   g_last_closed=latest;
  }

void OnDeinit(const int reason)
  {
   // The tester may stop immediately before the first tick of the next bar.
   // Finalize the last bounded M5 bar only when the explicit cutoff proves its
   // full interval is inside the admitted observation window.
   if(g_observers_ready && g_data!=INVALID_HANDLE)
     {
      const datetime final_bar=iTime(_Symbol,PERIOD_M5,0);
      if(final_bar>g_last_closed &&
         final_bar+PeriodSeconds(PERIOD_M5)<=InpDeterministicCutoff)
        {
         EmitClosedBar(final_bar);
         g_last_closed=final_bar;
         g_finalized_bar_rows=RANGE_COUNT;
        }
     }

   for(int i=0;i<RANGE_COUNT;i++)
      if(g_handles[i]!=INVALID_HANDLE)
         IndicatorRelease(g_handles[i]);

   if(g_receipt!=INVALID_HANDLE)
     {
      FileWrite(g_receipt,SCHEMA,InpInvocationTag,_Symbol,EnumToString(PERIOD_M5),
                IntegerToString(InpStartHour),IntegerToString(InpStartMinute),
                IntegerToString(InpAreaEndHour),IntegerToString(InpAreaEndMinute),
                IntegerToString(g_handles_ok),LongText(g_rows),LongText(g_copy_failures),
                LongText(g_readiness_deferrals),LongText(g_finalized_bar_rows),
                IntegerToString(reason));
      FileFlush(g_receipt);
      FileClose(g_receipt);
     }
   if(g_data!=INVALID_HANDLE)
     {
      FileFlush(g_data);
      FileClose(g_data);
     }
  }
