/// next/link 的兼容实现(基于 React Router 的 Link)。
///
/// 设计意图:
///   next/link 与 react-router-dom 的 Link 用法几乎一致(都是 <Link href/to>),
///   唯一差别是属性名:next 用 href,RR 用 to。这里包一层做属性映射,
///   让组件里的 <Link href="..."> 原样可用。通过 vite alias 指向本文件。

import { forwardRef } from 'react'
import { Link as RRLink, type LinkProps as RRLinkProps } from 'react-router-dom'

interface NextLinkProps extends Omit<RRLinkProps, 'to'> {
  href: string
  /// next/link 特有:子元素自定义 <a>(如按钮)时透传 href;
  /// RR 的 Link 本就渲染 <a>,这里接收并忽略,不透传给 DOM(RR 不认)。
  passHref?: boolean
}

/// 把 next 的 href 映射为 React Router 的 to,其余属性透传。
const Link = forwardRef<HTMLAnchorElement, NextLinkProps>(function Link(
  { href, passHref: _passHref, ...rest },
  ref
) {
  return <RRLink ref={ref} to={href} {...rest} />
})

export default Link
