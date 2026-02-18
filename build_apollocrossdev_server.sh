#!/bin/bash

cd Amiga
make clean
make -j16
cd ..
make clean