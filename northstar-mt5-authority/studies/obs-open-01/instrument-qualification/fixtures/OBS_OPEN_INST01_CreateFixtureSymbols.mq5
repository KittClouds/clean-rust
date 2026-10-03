//+------------------------------------------------------------------+
//| OBS_OPEN_INST01_CreateFixtureSymbols.mq5                         |
//| Creates deterministic custom-symbol OHLC fixtures for metrology.|
//+------------------------------------------------------------------+
#property script_show_inputs
#property strict

input string InpTemplateSymbol = "US30";
input string InpFullSymbol = "OBSINST01_FULL";
input string InpGapSymbol = "OBSINST01_GAP";

const datetime FIXTURE_BEGIN = D'2024.01.02 09:20:00';
const int FIXTURE_BARS = 61;

void SetBar(MqlRates &rate,
            const datetime time,
            const double open,
            const double high,
            const double low,
            const double close)
{
   rate.time = time;
   rate.open = open;
   rate.high = high;
   rate.low = low;
   rate.close = close;
   rate.tick_volume = 4;
   rate.spread = 1;
   rate.real_volume = 0;
}

void DefineMetrologyPath(MqlRates &rates[])
{
   ArrayResize(rates, FIXTURE_BARS);
   for(int i = 0; i < FIXTURE_BARS; ++i)
   {
      const double base = 100.0 + 0.01 * (double)i;
      SetBar(rates[i], FIXTURE_BEGIN + i * 60, base, base + 0.20, base - 0.20, base + 0.05);
   }

   // Index 10 is 09:30. These bars intentionally exercise the complete
   // strict/equality/simultaneous/ordinary candidate state surface.
   SetBar(rates[10], D'2024.01.02 09:30:00', 100.0, 101.0,  99.0, 100.0); // first H/L #1
   SetBar(rates[11], D'2024.01.02 09:31:00', 100.0, 102.0,  99.5, 101.0); // strict H
   SetBar(rates[12], D'2024.01.02 09:32:00', 101.0, 101.5,  98.0,  99.0); // strict L
   SetBar(rates[13], D'2024.01.02 09:33:00',  99.0, 103.0,  97.0, 100.0); // simultaneous H/L
   SetBar(rates[14], D'2024.01.02 09:34:00', 100.0, 103.0,  97.0, 101.0); // exact equality

   // Frozen range authority commits at 09:35. Later bars test fixed-range
   // extension and age behavior without altering the range.
   SetBar(rates[15], D'2024.01.02 09:35:00', 101.0, 102.0,  98.0, 100.0); // ordinary
   SetBar(rates[16], D'2024.01.02 09:36:00', 100.0, 104.0,  98.0, 103.0); // post-freeze H
   SetBar(rates[17], D'2024.01.02 09:37:00', 103.0, 103.5,  96.0,  97.0); // post-freeze L
   SetBar(rates[18], D'2024.01.02 09:38:00',  97.0, 103.0,  97.0, 100.0); // ordinary
   SetBar(rates[19], D'2024.01.02 09:39:00', 100.0, 104.0,  96.0, 101.0); // equality

   // Endpoint-containing candles deliberately establish late extremes.
   SetBar(rates[29], D'2024.01.02 09:49:00', 101.0, 105.0,  95.0, 100.0);
   SetBar(rates[39], D'2024.01.02 09:59:00', 100.0, 106.0,  94.0, 101.0);
}

void SetTick(MqlTick &tick, const long time_msc, const double price)
{
   ZeroMemory(tick);
   tick.time_msc = time_msc;
   tick.time = (datetime)(time_msc / 1000);
   tick.bid = price;
   tick.ask = price + 0.01;
   tick.last = price;
   tick.volume = 1;
   tick.volume_real = 1.0;
   tick.flags = TICK_FLAG_BID | TICK_FLAG_ASK | TICK_FLAG_LAST;
}

int ReplaceFixtureTicks(const string symbol, const MqlRates &rates[])
{
   MqlTick ticks[];
   const int ticks_per_bar = 4;
   ArrayResize(ticks, ArraySize(rates) * ticks_per_bar);
   for(int i = 0; i < ArraySize(rates); ++i)
   {
      const long base = (long)rates[i].time * 1000;
      SetTick(ticks[i * ticks_per_bar + 0], base,         rates[i].open);
      SetTick(ticks[i * ticks_per_bar + 1], base + 15000, rates[i].high);
      SetTick(ticks[i * ticks_per_bar + 2], base + 30000, rates[i].low);
      SetTick(ticks[i * ticks_per_bar + 3], base + 45000, rates[i].close);
   }
   ResetLastError();
   return CustomTicksReplace(symbol,
                             ticks[0].time_msc,
                             ticks[ArraySize(ticks) - 1].time_msc,
                             ticks);
}

bool RecreateSymbol(const string symbol, const MqlRates &source[], const int omitted_index)
{
   SymbolSelect(symbol, false);
   CustomSymbolDelete(symbol); // A missing prior symbol is harmless here.
   ResetLastError();
   if(!CustomSymbolCreate(symbol, "OBS_OPEN_INST01", InpTemplateSymbol))
   {
      PrintFormat("INST01_FIXTURE_CREATE_FAIL symbol=%s error=%d", symbol, GetLastError());
      return false;
   }
   SymbolSelect(symbol, true);

   MqlRates admitted[];
   ArrayResize(admitted, ArraySize(source) - (omitted_index >= 0 ? 1 : 0));
   int write = 0;
   for(int i = 0; i < ArraySize(source); ++i)
   {
      if(i == omitted_index)
         continue;
      admitted[write++] = source[i];
   }
   ResetLastError();
   const int stored = CustomRatesReplace(symbol,
                                         admitted[0].time,
                                         admitted[ArraySize(admitted) - 1].time,
                                         admitted);
   if(stored != ArraySize(admitted))
   {
      PrintFormat("INST01_FIXTURE_RATES_FAIL symbol=%s expected=%d stored=%d error=%d",
                  symbol, ArraySize(admitted), stored, GetLastError());
      return false;
   }
   const int ticks = ReplaceFixtureTicks(symbol, admitted);
   if(ticks != ArraySize(admitted) * 4)
   {
      PrintFormat("INST01_FIXTURE_TICKS_FAIL symbol=%s expected=%d stored=%d error=%d",
                  symbol, ArraySize(admitted) * 4, ticks, GetLastError());
      return false;
   }
   PrintFormat("INST01_FIXTURE_PASS symbol=%s bars=%d ticks=%d omitted_index=%d begin=%I64d end=%I64d",
               symbol, stored, ticks, omitted_index,
               (long)admitted[0].time, (long)admitted[ArraySize(admitted) - 1].time);
   return true;
}

void OnStart()
{
   MqlRates fixture[];
   DefineMetrologyPath(fixture);
   const bool full = RecreateSymbol(InpFullSymbol, fixture, -1);
   // Omit 09:36, a bar which contains the first post-freeze strict new high.
   const bool gap = RecreateSymbol(InpGapSymbol, fixture, 16);
   PrintFormat("INST01_FIXTURE_ROOT full=%s gap=%s", full ? "PASS" : "FAIL", gap ? "PASS" : "FAIL");
}
