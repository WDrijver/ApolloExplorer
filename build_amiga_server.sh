#!/bin/bash

#The version comes from VERSION_STRING in protocolTypes.h, so it never goes stale here
VERSION="$(sed -n 's/^#define VERSION_STRING "\(.*\)"/\1/p' "$(dirname "$0")/protocolTypes.h")"

printf '\33c\e[3J'
echo ""
echo -e "\033[1m\033[37m########## \033[31mApollo\033[1;30mExplorer Amiga Server - Release ${VERSION} \033[37m###########\033[0m\033[36m"
echo ""

rm  -f log.txt
rm -r -f ApolloExplorer-Amiga >>log.txt 2>>log.txt

cd Amiga
echo -e "\033[1m\033[37m1. Clean House\033[0m"
make clean >>log.txt 2>>log.txt
echo -e "\033[1m\033[37m2. Make Project\033[0m"
make all -j16 >>log.txt 2>>log.txt
echo ""
cd ..

mkdir -p ApolloExplorer-Amiga
mv Amiga/ApolloExplorerSrv ApolloExplorer-Amiga/ApolloExplorerSrv >>log.txt 2>>log.txt
mv Amiga/ApolloExplorerTool ApolloExplorer-Amiga/ApolloExplorerTool >>log.txt 2>>log.txt
