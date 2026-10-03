//+------------------------------------------------------------------+
//| OBS_OPEN_ClockProbe_v1.mq5                                      |
//| Read-only source-clock and symbol-session qualification probe.   |
//+------------------------------------------------------------------+
#property script_show_inputs
#property version   "1.00"

input string InpSourceSymbol = "US30";
input string InpReceiptName  = "OBS_OPEN_01_clock_probe_live.tsv";

void WriteKV(const int handle, const string key, const string value)
{
   FileWrite(handle, key, value);
}

string BoolText(const bool value)
{
   return value ? "true" : "false";
}

string TimeText(const datetime value)
{
   return TimeToString(value, TIME_DATE | TIME_SECONDS);
}

string LongText(const long value)
{
   return StringFormat("%I64d", value);
}

string DayName(const ENUM_DAY_OF_WEEK day)
{
   switch(day)
   {
      case SUNDAY:    return "SUNDAY";
      case MONDAY:    return "MONDAY";
      case TUESDAY:   return "TUESDAY";
      case WEDNESDAY: return "WEDNESDAY";
      case THURSDAY:  return "THURSDAY";
      case FRIDAY:    return "FRIDAY";
      case SATURDAY:  return "SATURDAY";
   }
   return "UNKNOWN";
}

void WriteSessions(const int handle,
                   const string symbol,
                   const bool trade_sessions)
{
   for(int day_index = (int)SUNDAY; day_index <= (int)SATURDAY; ++day_index)
   {
      const ENUM_DAY_OF_WEEK day = (ENUM_DAY_OF_WEEK)day_index;
      for(uint session_index = 0; session_index < 32; ++session_index)
      {
         datetime from_time = 0;
         datetime to_time = 0;
         const bool found = trade_sessions
                            ? SymbolInfoSessionTrade(symbol, day, session_index,
                                                     from_time, to_time)
                            : SymbolInfoSessionQuote(symbol, day, session_index,
                                                     from_time, to_time);
         if(!found)
            break;

         const string prefix = trade_sessions ? "trade_session" : "quote_session";
         const string key = StringFormat("%s.%s.%u",
                                         prefix, DayName(day), session_index);
         const string value = StringFormat("%I64d|%I64d|%s|%s",
                                           (long)from_time,
                                           (long)to_time,
                                           TimeText(from_time),
                                           TimeText(to_time));
         WriteKV(handle, key, value);
      }
   }
}

void OnStart()
{
   const string symbol = InpSourceSymbol;
   const datetime time_current = TimeCurrent();
   const datetime time_trade_server = TimeTradeServer();
   const datetime time_gmt = TimeGMT();
   const datetime time_local = TimeLocal();

   ResetLastError();
   const int handle = FileOpen(InpReceiptName,
                               FILE_COMMON | FILE_WRITE | FILE_CSV | FILE_ANSI,
                               '\t');
   if(handle == INVALID_HANDLE)
   {
      PrintFormat("OBS_OPEN_CLOCK_PROBE ERROR file_open=%d name=%s",
                  GetLastError(), InpReceiptName);
      return;
   }

   WriteKV(handle, "receipt_schema", "OBS_OPEN_CLOCK_PROBE_V1");
   WriteKV(handle, "probe_scope", "CURRENT_LIVE_INSTANT_ONLY");
   WriteKV(handle, "historical_offset_authority", "NOT_ESTABLISHED");
   WriteKV(handle, "source_symbol", symbol);
   WriteKV(handle, "terminal_company", TerminalInfoString(TERMINAL_COMPANY));
   WriteKV(handle, "terminal_name", TerminalInfoString(TERMINAL_NAME));
   WriteKV(handle, "terminal_build", IntegerToString((int)TerminalInfoInteger(TERMINAL_BUILD)));
   WriteKV(handle, "account_server_source_id", AccountInfoString(ACCOUNT_SERVER));
   WriteKV(handle, "terminal_connected", BoolText((bool)TerminalInfoInteger(TERMINAL_CONNECTED)));
   WriteKV(handle, "mql_tester", BoolText((bool)MQLInfoInteger(MQL_TESTER)));
   WriteKV(handle, "mql_visual_mode", BoolText((bool)MQLInfoInteger(MQL_VISUAL_MODE)));

   WriteKV(handle, "time_current_epoch", LongText((long)time_current));
   WriteKV(handle, "time_current_text", TimeText(time_current));
   WriteKV(handle, "time_trade_server_epoch", LongText((long)time_trade_server));
   WriteKV(handle, "time_trade_server_text", TimeText(time_trade_server));
   WriteKV(handle, "time_gmt_epoch", LongText((long)time_gmt));
   WriteKV(handle, "time_gmt_text", TimeText(time_gmt));
   WriteKV(handle, "time_local_epoch", LongText((long)time_local));
   WriteKV(handle, "time_local_text", TimeText(time_local));
   WriteKV(handle, "source_minus_gmt_seconds",
           LongText((long)time_current - (long)time_gmt));
   WriteKV(handle, "trade_server_minus_gmt_seconds",
           LongText((long)time_trade_server - (long)time_gmt));
   WriteKV(handle, "time_gmt_offset_raw_seconds", IntegerToString(TimeGMTOffset()));
   WriteKV(handle, "time_daylight_savings_raw_seconds",
           IntegerToString(TimeDaylightSavings()));

   WriteKV(handle, "symbol_description", SymbolInfoString(symbol, SYMBOL_DESCRIPTION));
   WriteKV(handle, "symbol_path", SymbolInfoString(symbol, SYMBOL_PATH));
   WriteKV(handle, "symbol_currency_base", SymbolInfoString(symbol, SYMBOL_CURRENCY_BASE));
   WriteKV(handle, "symbol_currency_profit", SymbolInfoString(symbol, SYMBOL_CURRENCY_PROFIT));
   WriteKV(handle, "symbol_digits", IntegerToString((int)SymbolInfoInteger(symbol, SYMBOL_DIGITS)));
   WriteKV(handle, "symbol_tick_size",
           DoubleToString(SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE), 12));
   WriteKV(handle, "symbol_point", DoubleToString(SymbolInfoDouble(symbol, SYMBOL_POINT), 12));
   WriteKV(handle, "symbol_last_quote_epoch",
           LongText((long)SymbolInfoInteger(symbol, SYMBOL_TIME)));

   WriteSessions(handle, symbol, true);
   WriteSessions(handle, symbol, false);

   FileFlush(handle);
   FileClose(handle);

   PrintFormat("OBS_OPEN_CLOCK_PROBE COMPLETE name=%s source=%s current=%s gmt=%s delta=%I64d",
               InpReceiptName,
               symbol,
               TimeText(time_current),
               TimeText(time_gmt),
               (long)time_current - (long)time_gmt);
}
