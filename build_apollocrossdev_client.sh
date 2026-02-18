#!/bin/bash

clear
make clean
qmake
make -j16
make clean

sudo cp ApolloExplorerPC/ApolloExplorer /opt/ApolloExplorer/bin/ApolloExplorer
sudo cp ApolloExplorerPC/ApolloExplorer.desktop /usr/share/applications/ApolloExplorer.desktop