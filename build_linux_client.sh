#!/bin/bash

clear
qmake -recursive
make clean
make -j16
make clean

sudo cp ApolloExplorerPC/ApolloExplorer /opt/ApolloExplorer/bin/ApolloExplorer
sudo cp ApolloExplorerPC/ApolloExplorer.desktop /usr/share/applications/ApolloExplorer.desktop