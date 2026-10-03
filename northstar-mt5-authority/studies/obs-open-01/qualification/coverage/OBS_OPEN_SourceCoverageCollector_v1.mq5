//+------------------------------------------------------------------+
//| OBS_OPEN_SourceCoverageCollector_v1.mq5                          |
//| Qualification-only export of source bars. No observer semantics. |
//+------------------------------------------------------------------+
#property script_show_inputs
#property strict

input string InpSymbol      = "US30";
input string InpFromDate    = "2024.01.01";
input string InpThroughDate = "2025.12.31";
input int    InpRetryCount  = 120;
input int    InpRetryMs     = 250;

const string SCHEMA = "OBS_OPEN_SOURCE_COVERAGE_V1";

string LongText(const long value)
  {
   return StringFormat("%I64d",value);
  }

string PriceText(const double value)
  {
   const int digits=(int)SymbolInfoInteger(InpSymbol,SYMBOL_DIGITS);
   return DoubleToString(value,digits);
  }

int CopyRange(const ENUM_TIMEFRAMES timeframe,
              const datetime from,
              const datetime through,
              MqlRates &rates[],
              int &error_code)
  {
   int copied=-1;
   for(int attempt=0;attempt<=InpRetryCount;attempt++)
     {
      ResetLastError();
      copied=CopyRates(InpSymbol,timeframe,from,through,rates);
      error_code=GetLastError();
      if(copied>=0)
         return copied;
      if(attempt<InpRetryCount)
         Sleep(InpRetryMs);
     }
   return copied;
  }

bool ExportRange(const int bars_handle,
                 const int census_handle,
                 const datetime first_day,
                 const datetime last_day,
                 const ENUM_TIMEFRAMES timeframe,
                 const string timeframe_name)
  {
   MqlRates rates[];
   ArraySetAsSeries(rates,false);
   int error_code=0;
   const int copied=CopyRange(timeframe,first_day,last_day+86399,rates,error_code);
   if(copied<0)
     {
      Print("OBS_OPEN_SOURCE_COVERAGE copy failed timeframe=",timeframe_name,
            " error=",error_code);
      return false;
     }

   int cursor=0;
   for(datetime day=first_day;day<=last_day;day+=86400)
     {
      const datetime through=day+86399;
      const int begin=cursor;
      while(cursor<copied && rates[cursor].time<=through)
        {
         const MqlRates rate=rates[cursor];
         FileWrite(bars_handle,
                   SCHEMA,
                   TimeToString(day,TIME_DATE),
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
         cursor++;
        }

      const int count=cursor-begin;
      const string first_time=(count>0)
                              ? TimeToString(rates[begin].time,TIME_DATE|TIME_SECONDS)
                              : "";
      const string last_time=(count>0)
                             ? TimeToString(rates[cursor-1].time,TIME_DATE|TIME_SECONDS)
                             : "";
      FileWrite(census_handle,
                TimeToString(day,TIME_DATE),
                timeframe_name,
                IntegerToString(count),
                IntegerToString(error_code),
                first_time,
                last_time);
     }

   Print("OBS_OPEN_SOURCE_COVERAGE_RANGE timeframe=",timeframe_name,
         " copied=",copied);
   return true;
  }

void OnStart()
  {
   if(!SymbolSelect(InpSymbol,true))
     {
      Print("OBS_OPEN_SOURCE_COVERAGE symbol selection failed: ",InpSymbol);
      return;
     }

   const datetime first_day=StringToTime(InpFromDate+" 00:00:00");
   const datetime last_day=StringToTime(InpThroughDate+" 00:00:00");
   if(first_day<=0 || last_day<first_day)
     {
      Print("OBS_OPEN_SOURCE_COVERAGE invalid date interval");
      return;
     }

   const int bars_handle=FileOpen("OBS_OPEN_01_source_bars.tsv",
                                  FILE_COMMON|FILE_WRITE|FILE_CSV|FILE_ANSI,
                                  '\t');
   const int census_handle=FileOpen("OBS_OPEN_01_source_daily_census.tsv",
                                    FILE_COMMON|FILE_WRITE|FILE_CSV|FILE_ANSI,
                                    '\t');
   if(bars_handle==INVALID_HANDLE || census_handle==INVALID_HANDLE)
     {
      Print("OBS_OPEN_SOURCE_COVERAGE file open failed: ",GetLastError());
      if(bars_handle!=INVALID_HANDLE) FileClose(bars_handle);
      if(census_handle!=INVALID_HANDLE) FileClose(census_handle);
      return;
     }

   FileWrite(bars_handle,
             "schema","source_day","timeframe","server_epoch","server_time",
             "open","high","low","close","tick_volume","spread","real_volume");
   FileWrite(census_handle,
             "source_day","timeframe","copied","error_code",
             "first_server_time","last_server_time");

   const bool m1_ok=ExportRange(bars_handle,census_handle,
                                first_day,last_day,PERIOD_M1,"M1");
   const bool m5_ok=ExportRange(bars_handle,census_handle,
                                first_day,last_day,PERIOD_M5,"M5");

   FileFlush(bars_handle);
   FileFlush(census_handle);
   FileClose(bars_handle);
   FileClose(census_handle);

   Print("OBS_OPEN_SOURCE_COVERAGE_COMPLETE schema=",SCHEMA,
         " symbol=",InpSymbol,
         " from=",InpFromDate,
         " through=",InpThroughDate,
         " m1_ok=",m1_ok,
         " m5_ok=",m5_ok);
  }
