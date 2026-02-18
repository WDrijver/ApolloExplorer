#!/bin/bash

clear
/opt/homebrew/opt/qt@5/bin/qmake -recursive
make clean
make -j16
make clean

cp ApolloExplorerPC/icons/ApolloExplorer.icns ApolloExplorerPC/ApolloExplorer.app/Contents/Resources/