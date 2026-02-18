#!/bin/bash

clear
make clean

/opt/homebrew/opt/qt@5/bin/qmake
make -j16

make clean

sudo cp ApolloExplorerPC/ApolloExplorer /opt/ApolloExplorer/bin/ApolloExplorer
sudo cp ApolloExplorerPC/ApolloExplorer.desktop /usr/share/applications/ApolloExplorer.desktop