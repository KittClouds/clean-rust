//+------------------------------------------------------------------+
//| OBS_OPEN_SourceCoverageCollectorEA_v1.mq5                        |
//| Tester-only export of completed source bars. No observer state.  |
//+------------------------------------------------------------------+
#property strict
#property version "1.00"

input string InpFromDate    = "2024.01.01";
input string InpThroughDate = "2025.12.31";
input string InpOutputName  = "OBS_OPEN_01_source_bars.tsv";

const string SCHEMA = "OBS_OPEN_SOURCE_COVERAGE_V1";

int      g_handle=INVALID_HANDLE;
datetime g_from=0;
datetime g_through=0;
datetime g_last_m1=0;
datetime g_last_m5=0;
ulong    g_m1_rows=0;
ulong    g_m5_rows=0;

string LongText(const long value)
  {
   return StringFormat("%I64d",value);
  }

string PriceText(const double value)
  {
   return DoubleToString(value,(int)SymbolInfoInteger(_Symbol,SYMBOL_DIGITS));
  }

bool EmitClosedBar(const ENUM_TIMEFRAMES timeframe,const string timeframe_name)
  {
   MqlRates rates[1];
   ResetLastError();
   const int copied=CopyRates(_Symbol,timeframe,1,1,rates);
   if(copied!=1)
     {
      Print("OBS_OPEN_SOURCE_COVERAGE_EA copy failed timeframe=",timeframe_name,
            " copied=",copied," error=",GetLastError());
      return false;
     }

   const MqlRates rate=rates[0];
   if(rate.time<g_from || rate.time>g_through)
      return true;

   FileWrite(g_handle,
             SCHEMA,
             TimeToString(rate.time,TIME_DATE),
             timeframe_name,
             LongText((long)rate.time),
             TimeToString(rate.time,TIME_DATE|TIME_SECONDS),
             PriceText(rate.open),
             PriceText(rate.high),
             PriceText(rate.low),
             PriceText(rate.close),
             LongText((long)rate.tick_volume),
             IntegerToString(rate.spread),
             LongText((long)rate.real_volume));

   if(timeframe==PERIOD_M1) g_m1_rows++;
   if(timeframe==PERIOD_M5) g_m5_rows++;
   return true;
  }

void ObserveTimeframe(const ENUM_TIMEFRAMES timeframe,
                      const string timeframe_name,
                      datetime &last_open)
  {
   const datetime current_open=iTime(_Symbol,timeframe,0);
   if(current_open<=0 || current_open==last_open)
      return;

   EmitClosedBar(timeframe,timeframe_name);
   last_open=current_open;
  }

int OnInit()
  {
   g_from=StringToTime(InpFromDate+" 00:00:00");
   g_through=StringToTime(InpThroughDate+" 23:59:59");
   if(g_from<=0 || g_through<g_from)
     {
      Print("OBS_OPEN_SOURCE_COVERAGE_EA invalid date interval");
      return INIT_PARAMETERS_INCORRECT;
     }

   g_handle=FileOpen(InpOutputName,
                     FILE_COMMON|FILE_WRITE|FILE_CSV|FILE_ANSI,
                     '\t');
   if(g_handle==INVALID_HANDLE)
     {
      Print("OBS_OPEN_SOURCE_COVERAGE_EA file open failed: ",GetLastError());
      return INIT_FAILED;
     }

   FileWrite(g_handle,
             "schema","source_day","timeframe","server_epoch","server_time",
             "open","high","low","close","tick_volume","spread","real_volume");
   Print("OBS_OPEN_SOURCE_COVERAGE_EA_START schema=",SCHEMA,
         " symbol=",_Symbol," from=",InpFromDate," through=",InpThroughDate);
   return INIT_SUCCEEDED;
  }

void OnTick()
  {
   ObserveTimeframe(PERIOD_M1,"M1",g_last_m1);
   ObserveTimeframe(PERIOD_M5,"M5",g_last_m5);
  }

void OnDeinit(const int reason)
  {
   if(g_handle!=INVALID_HANDLE)
     {
      FileFlush(g_handle);
      FileClose(g_handle);
      g_handle=INVALID_HANDLE;
     }
   Print("OBS_OPEN_SOURCE_COVERAGE_EA_COMPLETE schema=",SCHEMA,
         " reason=",reason,
         " m1_rows=",LongText((long)g_m1_rows),
         " m5_rows=",LongText((long)g_m5_rows));
  }

