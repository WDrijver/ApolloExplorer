printf '\33c\e[3J'
echo ""
echo -e "\033[1m\033[37m########## \033[31mApollo\033[1;30mExplorer MacOS Client - Release 1.3 \033[37m###########\033[0m\033[36m"
echo ""

echo -e "\033[1m\033[37m1. Checking Prerequisites\033[0m"

qmake
if [ $? -ne 0 ]; then
    echo -e "\033[1m\033[31mqmake not found\033[0m"
    echo -e "\033[1m\033[31mPlease install QT6 (homebrew, QT online installer or build from source)\033[0m"
    echo -e "\033[1m\033[31mand make sure qmake is in your PATH\033[0m"
    exit 1
fi


#brew install -qy qt@6 >>log.txt 2>>log.txt

echo -e "\033[1m\033[37m1. Clean House\033[0m"
rm -r -f .qmake.stash >log.txt 2>>log.txt
cd acp
make clean distclean >>log.txt 2>>log.txt
cd ../AmigaIconReader
make clean distclean >>log.txt 2>>log.txt
cd ../Amiga
make clean distclean >>log.txt 2>>log.txt
cd ../ApolloExplorerPC
make clean distclean >>log.txt 2>>log.txt
rm -r -f ApolloExplorer.zip >>log.txt 2>>log.txt
rm -r -f ApolloExplorer.dmg >>log.txt 2>>log.txt
cd ..

echo -e "\033[1m\033[37m2. QT6 Create macOS Project\033[0m"
qmake -recursive QMAKE_APPLE_DEVICE_ARCHS="x86_64 arm64" MACOSX_DEPLOYMENT_TARGET="12.7.6" >>log.txt 2>>log.txt

echo -e "\033[1m\033[37m3. Make macOS Project\033[0m"
make -j16 >>log.txt 2>>log.txt

echo -e "\033[1m\033[37m4. Clean Project\033[0m"
cd acp
make clean >>log.txt 2>>log.txt
cd ../AmigaIconReader
make clean >>log.txt 2>>log.txt
cd ../Amiga
make clean >>log.txt 2>>log.txt
cd ../ApolloExplorerPC
make clean >>log.txt 2>>log.txt
cd ..

echo -e "\033[1;30m"
printf 'Proceeed with Signing, Notarization and Packaging?\nRequires Apple Developer Team-ID in ${APPLETEAMID}\nChoose No unless you understand the question (y/n)? '
read answer
if [ "$answer" != "${answer#[Yy]}" ] ;then 
    echo ""
    cd ApolloExplorerPC
    
    echo -e "\033[1m\033[37mA. QT Deploy MacOS with static Libs + Hardening + Signing\033[0m"
    macdeployqt ApolloExplorer.app -verbose=2 -sign-for-notarization=${APPLETEAMID} >>log.txt 2>>log.txt

    echo -e "\033[1m\033[37mB. ZIP ApolloExplorer.app Bundle (keep Symlinks intact)\033[0m"
    zip -r -y ApolloExplorer.zip ApolloExplorer.app >>log.txt 2>>log.txt
    
    echo -e "\033[1m\033[37mC. Notarize ApolloExplorer.app Bundle with Apple Developer ID (${APPLETEAMID})\033[1;30m\n"
    xcrun notarytool submit ApolloExplorer.zip --keychain-profile "AC_PASSWORD" --wait   

    echo -e "\033[1m\033[37mD. Staple ApolloExplorer.app Bundle with Notarization Ticket\033[1;30m\n"
    xcrun stapler staple ApolloExplorer.app  

    echo -e "\n\033[1m\033[37mE. Cleanup & Finish\033[0m\n"
    rm -r -f ApolloExplorer.zip
    cd ..
fi

cp icons/Icon? ApolloExplorerPC/ApolloExplorer.app
echo ""