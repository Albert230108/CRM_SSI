1. open ubuntu from terminal
2. 
3. rsync -av --exclude="node_modules" "/mnt/c/Users/Alberto/Documents/Coding Projects/CRM from Github/CRM_SSI/mobile/" ~/mobile/
4. cd ~/mobile
npx eas-cli build -p android --profile preview --local
5. cp *.apk "/mnt/c/Users/Alberto/Desktop/"