#!/bin/bash

clear
/opt/homebrew/opt/qt@5/bin/qmake -recursive
make clean
make -j16
make clean

cp icons/ApolloExplorer.icns build/ApolloExplorer.app/Contents/Resources/