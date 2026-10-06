# 本机读 OSS 走公网域名

`oss-*-internal` 只在阿里云 VPC 内可解析。本机 `APP_ENV` 不是 production 时，服务端检查、读取、删除对象改走公网 endpoint。预签名上传地址仍用公网，手机不受影响。生产环境继续用内网 endpoint。
