//+------------------------------------------------------------------+
//| OBS_OPEN_ParameterEchoProbe_v1.mq5                              |
//| Tests the tester's custom-indicator input ABI without science.  |
//+------------------------------------------------------------------+
#property strict
#property tester_indicator "OBS_OPEN_ParameterEcho_v1.ex5"

int g_handles[5];

void ReportHandle(const string label,const int handle)
  {
   Print("OBS_OPEN_ABI_HANDLE variant=",label," handle=",handle,
         " error=",GetLastError());
  }

int OnInit()
  {
   ResetLastError();
   g_handles[0]=iCustom(_Symbol,PERIOD_M5,"OBS_OPEN_ParameterEcho_v1");
   ReportHandle("DEFAULT",g_handles[0]);

   ResetLastError();
   g_handles[1]=iCustom(_Symbol,PERIOD_M5,"OBS_OPEN_ParameterEcho_v1",
                        16,30,5,23,0,3);
   ReportHandle("SIX",g_handles[1]);

   ResetLastError();
   g_handles[2]=iCustom(_Symbol,PERIOD_M5,"OBS_OPEN_ParameterEcho_v1",
                        16,30,5,23,0,3,true,true,false,false,false,false);
   ReportHandle("TWELVE",g_handles[2]);

   ResetLastError();
   g_handles[3]=iCustom(_Symbol,PERIOD_M5,"OBS_OPEN_ParameterEcho_v1",
                        "Opening Range Clock",16,30,5,23,0,3,
                        "Coverage Contract",true,true,
                        "Original-Style Drawing",false,false,false,false,
                        clrRed,clrViolet,clrMediumPurple,32,12,1,
                        STYLE_SOLID,"FULL_GROUPED_ABI");
   ReportHandle("TWENTY_THREE_GROUPED",g_handles[3]);

   ResetLastError();
   g_handles[4]=iCustom(_Symbol,PERIOD_M5,"OBS_OPEN_ParameterEcho_v1",
                        16,30,5,23,0,3,true,true,false,false,false,false,
                        clrRed,clrViolet,clrMediumPurple,32,12,1,
                        STYLE_SOLID,"FULL");
   ReportHandle("TWENTY",g_handles[4]);
   return INIT_SUCCEEDED;
  }

void OnTick()
  {
  }

void OnDeinit(const int reason)
  {
   for(int i=0;i<ArraySize(g_handles);i++)
      if(g_handles[i]!=INVALID_HANDLE)
         IndicatorRelease(g_handles[i]);
  }
