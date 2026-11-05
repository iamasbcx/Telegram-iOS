import CryptoKit
import Foundation

/// 编译期固定密码的校验值，由 tools/configure-calculator-passcode.py 生成。
/// 仅用于入口访问控制；短数字密码可被离线枚举，不作为数据加密密钥。
enum CalculatorGateConfiguration {
    private static let salt = "5f3f1608193640424eb41aa0083b1559"
    private static let digitCount = 7
    private static let digest: [UInt8] = [0x80, 0x55, 0x1d, 0xe4, 0xc7, 0xc1, 0xd0, 0x1b, 0x83, 0x5e, 0xb7, 0x93, 0x6a, 0xfb, 0x56, 0x2b, 0xd1, 0xb8, 0xfa, 0x58, 0x47, 0x73, 0x86, 0xdd, 0xa3, 0x87, 0xd0, 0x6f, 0x4f, 0xa3, 0xe3, 0x7f]

    static func matches(_ candidate: String) -> Bool {
        let bytes = Array(candidate.utf8)
        guard bytes.count == self.digitCount, bytes.allSatisfy({ $0 >= 48 && $0 <= 57 }) else {
            return false
        }
        let actual = SHA256.hash(data: Data((self.salt + ":" + candidate).utf8))
        var difference: UInt8 = 0
        for (left, right) in zip(actual, self.digest) {
            difference |= left ^ right
        }
        return difference == 0
    }
}
