/// next/image 的兼容实现(退化为原生 <img>)。
///
/// 设计意图:
///   next/image 的核心价值是服务端图片优化(按需缩放、WebP、懒加载编排),
///   这依赖 Next 的服务端。SPA 中没有这套基础设施,最忠实的降级是直接渲染
///   原生 <img>:视觉与布局行为一致(保留 width/height/fill 的布局效果),
///   只是少了自动优化。本项目的图片多为搜索结果缩略图,影响不大。
///   通过 vite alias 把 'next/image' 指向本文件,组件无需改动。

import { forwardRef, type ImgHTMLAttributes } from 'react'

interface NextImageProps extends ImgHTMLAttributes<HTMLImageElement> {
  fill?: boolean
  priority?: boolean
  /// next/image 特有:跳过服务端优化。SPA 降级为原生 <img> 本就无优化,
  /// 接收并忽略(调用处大量使用,不改组件)。
  unoptimized?: boolean
}

const Image = forwardRef<HTMLImageElement, NextImageProps>(function Image(
  { fill, priority, unoptimized: _unoptimized, style, alt = '', ...rest },
  ref
) {
  // fill 模式:铺满父容器(父需为相对定位),对应 next/image 的 fill 行为
  const fillStyle: React.CSSProperties = fill
    ? {
        position: 'absolute',
        inset: 0,
        width: '100%',
        height: '100%',
        objectFit: 'cover'
      }
    : {}
  // priority 是 next 的预加载提示;原生用 loading="eager" 近似
  const loading = priority ? 'eager' : (rest.loading ?? 'lazy')
  return (
    <img
      ref={ref}
      alt={alt}
      style={{ ...fillStyle, ...style }}
      loading={loading}
      {...rest}
    />
  )
})

export default Image
