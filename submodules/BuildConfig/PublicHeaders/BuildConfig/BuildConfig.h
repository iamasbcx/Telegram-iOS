#import <Foundation/Foundation.h>

@interface DeviceSpecificEncryptionParameters : NSObject

@property (nonatomic, strong) NSData * _Nonnull key;
@property (nonatomic, strong) NSData * _Nonnull salt;

@end

@interface BuildConfig : NSObject

/// 编译期容器运行契约；为真时禁用依赖独立应用身份的系统服务，不影响相机、麦克风等用户授权。
@property (class, nonatomic, readonly) bool isContainerBuild;

- (instancetype _Nonnull)initWithBaseAppBundleId:(NSString * _Nonnull)baseAppBundleId;

@property (nonatomic, strong, readonly) NSString * _Nullable appCenterId;
@property (nonatomic, readonly) int32_t apiId;
@property (nonatomic, strong, readonly) NSString * _Nonnull apiHash;
@property (nonatomic, readonly) bool isInternalBuild;
@property (nonatomic, readonly) bool isAppStoreBuild;
@property (nonatomic, readonly) int64_t appStoreId;
@property (nonatomic, strong, readonly) NSString * _Nonnull appSpecificUrlScheme;
@property (nonatomic, readonly) bool isICloudEnabled;
@property (nonatomic, readonly) bool isSiriEnabled;

+ (NSString * _Nullable)keychainAccessGroupForBaseAppBundleId:(NSString * _Nonnull)baseAppBundleId NS_SWIFT_NAME(keychainAccessGroup(baseAppBundleId:));

+ (DeviceSpecificEncryptionParameters * _Nonnull)deviceSpecificEncryptionParameters:(NSString * _Nonnull)rootPath baseAppBundleId:(NSString * _Nonnull)baseAppBundleId;
- (NSData * _Nullable)bundleDataWithAppToken:(NSData * _Nullable)appToken tokenType:(NSString * _Nullable)tokenType tokenEnvironment:(NSString * _Nullable)tokenEnvironment signatureDict:(NSDictionary * _Nullable)signatureDict;

+ (void)getHardwareEncryptionAvailableWithBaseAppBundleId:(NSString * _Nonnull)baseAppBundleId completion:(void (^ _Nonnull)(NSData * _Nullable))completion;
+ (void)encryptApplicationSecret:(NSData * _Nonnull)secret baseAppBundleId:(NSString * _Nonnull)baseAppBundleId completion:(void (^ _Nonnull)(NSData * _Nullable, NSData * _Nullable))completion;
+ (void)decryptApplicationSecret:(NSData * _Nonnull)secret publicKey:(NSData * _Nonnull)publicKey baseAppBundleId:(NSString * _Nonnull)baseAppBundleId completion:(void (^ _Nonnull)(NSData * _Nullable, bool))completion;

@end
