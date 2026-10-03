//+------------------------------------------------------------------+
//| OBS_OPEN_BrokerBarsProbe_v1.mq5                                  |
//| Qualification-only export of bounded broker/server bar windows.  |
//+------------------------------------------------------------------+
#property script_show_inputs
#property strict

input string InpSymbol = "US30";

const string PROBE_SCHEMA = "OBS_OPEN_BROKER_BARS_PROBE_V1";

string AnchorDates[] =
  {
   "2025.01.15", "2025.03.07", "2025.03.14", "2025.04.04",
   "2025.10.24", "2025.10.31", "2025.11.07",
   "2026.01.14", "2026.03.06", "2026.03.13", "2026.04.03",
   "2026.08.13"
  };

string LongText(const long value)
  {
   return StringFormat("%I64d", value);
  }

string PriceText(const double value)
  {
   const int digits=(int)SymbolInfoInteger(InpSymbol,SYMBOL_DIGITS);
   return DoubleToString(value,digits);
  }

bool WriteRates(const ENUM_TIMEFRAMES timeframe,
                const string timeframe_name,
                const int bars_handle,
                const int receipt_handle,
                const string anchor_date)
  {
   const datetime from=StringToTime(anchor_date+" 00:00:00");
   const datetime through=from+86399;
   MqlRates rates[];
   ArraySetAsSeries(rates,false);
   ResetLastError();
   const int copied=CopyRates(InpSymbol,timeframe,from,through,rates);
   const int error_code=GetLastError();

   string first_time="";
   string last_time="";
   if(copied>0)
     {
      first_time=TimeToString(rates[0].time,TIME_DATE|TIME_SECONDS);
      last_time=TimeToString(rates[copied-1].time,TIME_DATE|TIME_SECONDS);
     }

   FileWrite(receipt_handle,
             anchor_date,
             timeframe_name,
             IntegerToString(copied),
             IntegerToString(error_code),
             first_time,
             last_time);

   if(copied<=0)
      return false;

   for(int i=0;i<copied;i++)
     {
      FileWrite(bars_handle,
                PROBE_SCHEMA,
                anchor_date,
                timeframe_name,
                LongText((long)rates[i].time),
                TimeToString(rates[i].time,TIME_DATE|TIME_SECONDS),
                PriceText(rates[i].open),
                PriceText(rates[i].high),
                PriceText(rates[i].low),
                PriceText(rates[i].close),
                LongText((long)rates[i].tick_volume),
                IntegerToString(rates[i].spread),
                LongText((long)rates[i].real_volume));
     }
   return true;
  }

void OnStart()
  {
   if(!SymbolSelect(InpSymbol,true))
     {
      Print("OBS_OPEN_BROKER_BARS_PROBE symbol selection failed: ",InpSymbol);
      return;
     }

   const int bars_handle=FileOpen("OBS_OPEN_01_broker_anchor_bars.tsv",
                                  FILE_COMMON|FILE_WRITE|FILE_CSV|FILE_ANSI,
                                  '\t');
   const int receipt_handle=FileOpen("OBS_OPEN_01_broker_anchor_receipt.tsv",
                                     FILE_COMMON|FILE_WRITE|FILE_CSV|FILE_ANSI,
                                     '\t');
   if(bars_handle==INVALID_HANDLE || receipt_handle==INVALID_HANDLE)
     {
      Print("OBS_OPEN_BROKER_BARS_PROBE file open failed: ",GetLastError());
      if(bars_handle!=INVALID_HANDLE) FileClose(bars_handle);
      if(receipt_handle!=INVALID_HANDLE) FileClose(receipt_handle);
      return;
     }

   FileWrite(bars_handle,
             "schema","anchor_date","timeframe","server_epoch","server_time",
             "open","high","low","close","tick_volume","spread","real_volume");
   FileWrite(receipt_handle,
             "anchor_date","timeframe","copied","error_code","first_server_time","last_server_time");

   int successful_windows=0;
   const int anchor_count=ArraySize(AnchorDates);
   for(int i=0;i<anchor_count;i++)
     {
      if(WriteRates(PERIOD_M1,"M1",bars_handle,receipt_handle,AnchorDates[i]))
         successful_windows++;
      if(WriteRates(PERIOD_M5,"M5",bars_handle,receipt_handle,AnchorDates[i]))
         successful_windows++;
     }

   FileFlush(bars_handle);
   FileFlush(receipt_handle);
   FileClose(bars_handle);
   FileClose(receipt_handle);

   Print("OBS_OPEN_BROKER_BARS_PROBE_COMPLETE schema=",PROBE_SCHEMA,
         " symbol=",InpSymbol,
         " anchors=",anchor_count,
         " successful_windows=",successful_windows,
         " expected_windows=",anchor_count*2);
  }
