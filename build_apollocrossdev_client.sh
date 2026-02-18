#!/bin/bash

clear
make clean
qmake
make -j16
make clean

