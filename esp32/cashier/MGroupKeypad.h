#pragma once
#include <Arduino.h>
#include <Keypad.h>

const byte M_GROUP_ROWS=4, M_GROUP_COLS=4;
char M_GROUPKeys[M_GROUP_ROWS][M_GROUP_COLS]={
  {'1','2','3','A'},
  {'4','5','6','B'},
  {'7','8','9','C'},
  {'*','0','#','D'}
};
byte M_GROUPRowPins[M_GROUP_ROWS]={32,33,25,26};
byte M_GROUPColPins[M_GROUP_COLS]={13,14,16,17};
Keypad M_GROUPKeypad=Keypad(makeKeymap(M_GROUPKeys),M_GROUPRowPins,M_GROUPColPins,M_GROUP_ROWS,M_GROUP_COLS);
